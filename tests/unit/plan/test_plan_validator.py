"""Unit tests for plan validation."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from application.ports.module_registry import ModuleRegistryReadPort
from application.registry.specs import MODULE_SPECS
from application.validation.settings import PlanValidationSettings
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from domain.entities.registry import (
    ModuleInput,
    ModuleMetadata,
    ModuleOutput,
    RegistrySnapshot,
)
from domain.errors import PlanValidationError
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe
from infrastructure.validation.plan_sizer import CanonicalPlanSizer
from infrastructure.validation.plan_validator import PlanValidator

_DEFAULT_SOURCE = PlanSource(operation="read_csv", params={"path": "input.csv"})
_DEFAULT_DESTINATION = PlanDestination(operation="save_csv", params={"path": "output.csv"})


def make_plan(
    *,
    source: PlanSource | None = _DEFAULT_SOURCE,
    transformations: Sequence[PlanTransformation] = (),
    destination: PlanDestination | None = _DEFAULT_DESTINATION,
    mode: str = "pipeline",
    approval_required: bool = True,
    chunk_size: int = 1000,
    on_error: str = "fail_fast",
) -> ExecutionPlan:
    return ExecutionPlan(
        plan_version="1.0",
        mode=mode,
        run_id="1729850000000-a1b2c3d4",
        name="test_plan",
        description="A test plan",
        source=source,
        transformations=transformations,
        destination=destination,
        chunking=PlanChunking(enabled=True, size=chunk_size),
        on_error=on_error,
        approval_required=approval_required,
    )


def make_assessment_plan(
    *,
    source: PlanSource | None = _DEFAULT_SOURCE,
    transformations: Sequence[PlanTransformation] = (),
) -> ExecutionPlan:
    return make_plan(
        source=source,
        transformations=transformations,
        destination=None,
        mode="assessment",
        approval_required=False,
    )


def _validator(
    workspace: Path,
    *,
    max_steps: int = 100,
    max_chunk_size: int = 10_000_000,
    max_plan_bytes: int = 1_000_000,
    max_path_length: int = 260,
) -> PlanValidator:
    return PlanValidator(
        build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS),
        workspace=FilesystemWorkspaceProbe(workspace),
        sizer=CanonicalPlanSizer(),
        settings=PlanValidationSettings(
            max_steps=max_steps,
            max_chunk_size=max_chunk_size,
            max_plan_bytes=max_plan_bytes,
            max_path_length=max_path_length,
        ),
    )


def _assert_code(plan: ExecutionPlan, code: str, *, workspace: Path | None = None) -> None:
    validator = _validator(workspace or Path.cwd())
    with pytest.raises(PlanValidationError) as caught:
        validator.validate(plan)
    assert caught.value.code == code


class _StubRegistry:
    def __init__(self, modules: Sequence[ModuleMetadata]) -> None:
        self._modules = {module.name: module for module in modules}

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(version="1.0.0", modules=tuple(self._modules.values()))

    def get(self, name: str, *, version: str | None = None) -> ModuleMetadata | None:
        return self._modules.get(name)

    def require(self, name: str, *, version: str | None = None) -> ModuleMetadata:
        module = self.get(name, version=version)
        if module is None:
            raise AssertionError(f"Unknown module: {name}")
        return module


def _fake_module(
    name: str,
    inputs: Sequence[ModuleInput],
    *,
    side_effects: tuple[str, ...] = (),
) -> ModuleMetadata:
    return ModuleMetadata(
        name=name,
        version="1.0.0",
        module="infrastructure.transformations.fake",
        function=name,
        description="Fake module for validation tests.",
        inputs=tuple(inputs),
        output=ModuleOutput(type="DataFrame", description="DataFrame"),
        dependencies=("dataframe",),
        side_effects=side_effects,
        examples=(),
        supports_chunking=False,
        idempotent=True,
        supported_dialects=(),
        security_notes="Test only.",
    )


def _fake_validator(module: ModuleMetadata, workspace: Path) -> PlanValidator:
    registry = cast(ModuleRegistryReadPort, _StubRegistry((module,)))
    return PlanValidator(
        registry,
        workspace=FilesystemWorkspaceProbe(workspace),
        sizer=CanonicalPlanSizer(),
    )


class _RecordingCheck:
    def __init__(self) -> None:
        self.validated: list[ExecutionPlan] = []

    def validate(self, plan: ExecutionPlan) -> None:
        self.validated.append(plan)


def test_injected_checks_replace_default_pipeline(tmp_path: Path) -> None:
    check = _RecordingCheck()
    validator = PlanValidator(
        build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS),
        workspace=FilesystemWorkspaceProbe(tmp_path),
        checks=(check,),
    )
    plan = make_plan()

    validator.validate(plan)

    assert check.validated == [plan]


def test_valid_pipeline_passes(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"], "policy": "both"},
            ),
        )
    )

    _validator(tmp_path).validate(plan)


def test_source_must_be_read_only_and_not_require_pipeline_input(tmp_path: Path) -> None:
    write_source = make_plan(source=PlanSource(operation="save_csv", params={"path": "output.csv"}))
    pipeline_source = make_plan(
        source=PlanSource(operation="trim_whitespace", params={"columns": ["name"]})
    )

    _assert_code(write_source, "PLAN_INVALID_OPERATION_ROLE", workspace=tmp_path)
    _assert_code(pipeline_source, "PLAN_INVALID_OPERATION_ROLE", workspace=tmp_path)


@pytest.mark.parametrize(
    ("operation", "params"),
    [
        ("read_csv", {"path": "input.csv"}),
        ("read_json", {"path": "input.json"}),
        ("save_csv", {"path": "output.csv"}),
    ],
)
def test_transformation_must_consume_pipeline_input_and_not_write(
    tmp_path: Path,
    operation: str,
    params: dict[str, object],
) -> None:
    plan = make_plan(
        transformations=(PlanTransformation(step_id="s1", operation=operation, params=params),)
    )

    _assert_code(plan, "PLAN_INVALID_OPERATION_ROLE", workspace=tmp_path)


def test_destination_must_be_a_write_operation(tmp_path: Path) -> None:
    plan = make_plan(destination=PlanDestination(operation="read_csv", params={"path": "copy.csv"}))

    _assert_code(plan, "PLAN_INVALID_OPERATION_ROLE", workspace=tmp_path)


def test_valid_payload_is_parsed_and_validated(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "plan_version": "1.0",
        "mode": "pipeline",
        "run_id": "1729850000000-a1b2c3d4",
        "name": "test_plan",
        "description": "A test plan",
        "source": {"operation": "read_csv", "params": {"path": "input.csv"}},
        "transformations": [],
        "destination": {"operation": "save_csv", "params": {"path": "output.csv"}},
        "chunking": {"enabled": True, "size": 1000},
        "on_error": "fail_fast",
        "approval_required": True,
    }

    _validator(tmp_path).validate(payload)


def test_valid_assessment_passes(tmp_path: Path) -> None:
    plan = make_assessment_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"]},
            ),
        )
    )

    _validator(tmp_path).validate(plan)


@pytest.mark.parametrize(
    ("operation", "params"),
    [
        ("read_json", {"path": "input.json"}),
        ("read_json", {"path": "input.json", "orient": "records"}),
        ("read_jsonl", {"path": "input.jsonl"}),
        ("read_parquet", {"path": "input.parquet"}),
        ("read_parquet", {"path": "input.parquet", "columns": ["id"]}),
    ],
)
def test_valid_ingestion_sources_pass(
    tmp_path: Path,
    operation: str,
    params: dict[str, object],
) -> None:
    plan = make_plan(source=PlanSource(operation=operation, params=params))

    _validator(tmp_path).validate(plan)


def test_unknown_operation_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(source=PlanSource(operation="unknown_operation", params={}))

    _assert_code(plan, "PLAN_UNKNOWN_OPERATION", workspace=tmp_path)


def test_unknown_argument_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"], "unexpected": True},
            ),
        )
    )

    _assert_code(plan, "PLAN_UNKNOWN_ARGUMENT", workspace=tmp_path)


def test_pipeline_managed_argument_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"df": None},
            ),
        )
    )

    _assert_code(plan, "PLAN_PIPELINE_ARGUMENT", workspace=tmp_path)


def test_missing_required_argument_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="cast_column",
                params={"target_type": "float"},
            ),
        )
    )

    _assert_code(plan, "PLAN_MISSING_ARGUMENT", workspace=tmp_path)


def test_invalid_argument_type_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="cast_column",
                params={"column": 1, "target_type": "float"},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT_TYPE", workspace=tmp_path)


def test_invalid_enum_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="cast_column",
                params={"column": "amount", "target_type": "date"},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT_TYPE", workspace=tmp_path)


@pytest.mark.parametrize("value", ["active", 1, 1.5])
def test_multi_union_argument_accepts_declared_types(
    tmp_path: Path,
    value: object,
) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="filter_rows",
                params={"column": "value", "operator": "equals", "value": value},
            ),
        )
    )

    _validator(tmp_path).validate(plan)


def test_multi_union_argument_rejects_undeclared_types(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="filter_rows",
                params={"column": "value", "operator": "equals", "value": True},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT_TYPE", workspace=tmp_path)


def test_filter_null_operator_rejects_a_value(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="filter_rows",
                params={"column": "status", "operator": "is_null", "value": "x"},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT", workspace=tmp_path)


def test_filter_comparison_requires_a_value(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="filter_rows",
                params={"column": "status", "operator": "equals"},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT", workspace=tmp_path)


def test_filter_text_operator_requires_a_string_value(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="filter_rows",
                params={"column": "status", "operator": "contains", "value": 1},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT", workspace=tmp_path)


def test_constant_imputation_requires_a_value(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="fill_missing_values",
                params={"column": "amount", "method": "constant"},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT", workspace=tmp_path)


def test_summary_imputation_rejects_a_value(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="fill_missing_values",
                params={"column": "amount", "method": "mean", "value": 0},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT", workspace=tmp_path)


def test_date_output_format_must_not_be_blank(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="normalize_dates",
                params={"column": "created_at", "output_format": "   "},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT", workspace=tmp_path)


def test_valid_transformation_semantics_pass(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="filter_rows",
                params={"column": "status", "operator": "is_not_null"},
            ),
            PlanTransformation(
                step_id="s2",
                operation="fill_missing_values",
                params={"column": "amount", "method": "constant", "value": 0},
            ),
            PlanTransformation(
                step_id="s3",
                operation="normalize_dates",
                params={"column": "created_at", "output_format": "%Y-%m-%d"},
            ),
        )
    )

    _validator(tmp_path).validate(plan)


def test_non_idempotent_transformation_is_rejected(tmp_path: Path) -> None:
    real_registry = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
    modules = {module.name: module for module in real_registry.snapshot().modules}
    fake = _fake_module(
        "fake_transform",
        (ModuleInput(name="df", type="DataFrame", required=True, pipeline_input=True),),
    )
    fake = replace(fake, idempotent=False)
    registry = cast(
        ModuleRegistryReadPort,
        _StubRegistry(
            (
                modules["read_csv"],
                fake,
                modules["save_csv"],
            )
        ),
    )
    validator = PlanValidator(
        registry,
        workspace=FilesystemWorkspaceProbe(tmp_path),
        sizer=CanonicalPlanSizer(),
    )
    plan = make_plan(
        transformations=(PlanTransformation(step_id="s1", operation="fake_transform", params={}),)
    )

    with pytest.raises(PlanValidationError) as caught:
        validator.validate(plan)

    assert caught.value.code == "PLAN_NON_IDEMPOTENT_TRANSFORMATION"
    assert caught.value.context == {
        "step": "transformation[s1]",
        "operation": "fake_transform",
    }


def test_empty_optional_argument_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": []},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT", workspace=tmp_path)


def test_blank_column_name_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="cast_column",
                params={"column": "   ", "target_type": "float"},
            ),
        )
    )

    _assert_code(plan, "PLAN_INVALID_ARGUMENT", workspace=tmp_path)


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("../secret.csv", "PLAN_PATH_TRAVERSAL"),
        ("sub/../secret.csv", "PLAN_PATH_TRAVERSAL"),
        ("/absolute/out.csv", "PLAN_PATH_NOT_ALLOWED"),
        ("C:\\temp\\out.csv", "PLAN_PATH_NOT_ALLOWED"),
        ("\\\\server\\share\\out.csv", "PLAN_PATH_NOT_ALLOWED"),
        ("~/out.csv", "PLAN_PATH_NOT_ALLOWED"),
        ("https://example.com/out.csv", "PLAN_INVALID_PATH"),
        ("bad\nname.csv", "PLAN_INVALID_PATH"),
        ("CON.txt", "PLAN_PATH_RESERVED_NAME"),
        ("nul", "PLAN_PATH_RESERVED_NAME"),
        ("data.", "PLAN_PATH_RESERVED_NAME"),
        ("data:stream.csv", "PLAN_PATH_NOT_ALLOWED"),
        ("a" * 256, "PLAN_PATH_TOO_LONG"),
    ],
)
def test_unsafe_paths_are_rejected(
    tmp_path: Path,
    path: str,
    code: str,
) -> None:
    plan = make_plan(source=PlanSource(operation="read_csv", params={"path": path}))

    _assert_code(plan, code, workspace=tmp_path)


def test_destination_path_is_validated(tmp_path: Path) -> None:
    plan = make_plan(
        destination=PlanDestination(operation="save_csv", params={"path": "../out.csv"})
    )

    _assert_code(plan, "PLAN_PATH_TRAVERSAL", workspace=tmp_path)


def test_path_must_stay_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not available on this platform")

    plan = make_plan(source=PlanSource(operation="read_csv", params={"path": "link/data.csv"}))

    _assert_code(plan, "PLAN_PATH_OUTSIDE_WORKSPACE", workspace=workspace)


def test_symlink_inside_workspace_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not available on this platform")

    plan = make_plan(source=PlanSource(operation="read_csv", params={"path": "link/data.csv"}))

    _assert_code(plan, "PLAN_PATH_SYMLINK", workspace=tmp_path)


def test_path_length_limit_is_enforced(tmp_path: Path) -> None:
    plan = make_plan(source=PlanSource(operation="read_csv", params={"path": "data.csv"}))

    with pytest.raises(PlanValidationError) as caught:
        _validator(tmp_path, max_path_length=5).validate(plan)

    assert caught.value.code == "PLAN_PATH_TOO_LONG"


def test_too_many_steps_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(step_id="s1", operation="trim_whitespace", params={}),
            PlanTransformation(step_id="s2", operation="trim_whitespace", params={}),
        )
    )

    with pytest.raises(PlanValidationError) as caught:
        _validator(tmp_path, max_steps=1).validate(plan)

    assert caught.value.code == "PLAN_TOO_MANY_STEPS"


def test_chunk_size_limit_is_enforced(tmp_path: Path) -> None:
    plan = make_plan(chunk_size=11)

    with pytest.raises(PlanValidationError) as caught:
        _validator(tmp_path, max_chunk_size=10).validate(plan)

    assert caught.value.code == "PLAN_INVALID_CHUNK_SIZE"


def test_plan_size_limit_is_enforced(tmp_path: Path) -> None:
    plan = make_plan()

    with pytest.raises(PlanValidationError) as caught:
        _validator(tmp_path, max_plan_bytes=10).validate(plan)

    assert caught.value.code == "PLAN_TOO_LARGE"


def test_unserializable_plan_is_rejected(tmp_path: Path) -> None:
    module = _fake_module(
        "custom_read",
        (ModuleInput(name="value", type="number", required=True),),
    )
    plan = make_assessment_plan(
        source=PlanSource(operation="custom_read", params={"value": float("nan")})
    )

    with pytest.raises(PlanValidationError) as caught:
        _fake_validator(module, tmp_path).validate(plan)

    assert caught.value.code == "PLAN_UNSERIALIZABLE"


def test_code_execution_content_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["eval(payload)"]},
            ),
        )
    )

    _assert_code(plan, "PLAN_UNSAFE_CONTENT", workspace=tmp_path)


def test_raw_sql_content_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["DROP TABLE users"]},
            ),
        )
    )

    _assert_code(plan, "PLAN_UNSAFE_CONTENT", workspace=tmp_path)


def test_forbidden_argument_key_is_rejected(tmp_path: Path) -> None:
    module = _fake_module(
        "custom_read",
        (ModuleInput(name="sql", type="string", required=True),),
    )
    plan = make_assessment_plan(
        source=PlanSource(operation="custom_read", params={"sql": "SELECT 1"})
    )

    with pytest.raises(PlanValidationError) as caught:
        _fake_validator(module, tmp_path).validate(plan)

    assert caught.value.code == "PLAN_UNSAFE_CONTENT"


def test_secret_argument_is_rejected(tmp_path: Path) -> None:
    module = _fake_module(
        "custom_read",
        (ModuleInput(name="password", type="string", required=True),),
    )
    plan = make_assessment_plan(
        source=PlanSource(operation="custom_read", params={"password": "hunter2"})
    )

    with pytest.raises(PlanValidationError) as caught:
        _fake_validator(module, tmp_path).validate(plan)

    assert caught.value.code == "PLAN_SECRET_IN_PARAMS"
    assert "hunter2" not in str(caught.value.context)


def test_write_without_approval_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(approval_required=False)

    _assert_code(plan, "PLAN_APPROVAL_REQUIRED", workspace=tmp_path)


def test_destructive_transformation_without_approval_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="drop_duplicate_rows",
                params={"subset": ["id"]},
            ),
        ),
        approval_required=False,
    )

    _assert_code(plan, "PLAN_APPROVAL_REQUIRED", workspace=tmp_path)


def test_coercing_cast_without_approval_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="cast_column",
                params={"column": "amount", "target_type": "float", "errors": "coerce"},
            ),
        ),
        approval_required=False,
    )

    _assert_code(plan, "PLAN_APPROVAL_REQUIRED", workspace=tmp_path)


def test_filter_rows_without_approval_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="filter_rows",
                params={"column": "status", "operator": "equals", "value": "active"},
            ),
        ),
        approval_required=False,
    )

    _assert_code(plan, "PLAN_APPROVAL_REQUIRED", workspace=tmp_path)


def test_coercing_date_normalization_without_approval_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="normalize_dates",
                params={
                    "column": "created_at",
                    "output_format": "%Y-%m-%d",
                    "errors": "coerce",
                },
            ),
        ),
        approval_required=False,
    )

    _assert_code(plan, "PLAN_APPROVAL_REQUIRED", workspace=tmp_path)


def test_null_replacement_without_approval_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="replace_values",
                params={"columns": ["status"], "old": "N/A", "new": None},
            ),
        ),
        approval_required=False,
    )

    _assert_code(plan, "PLAN_APPROVAL_REQUIRED", workspace=tmp_path)


def test_non_destructive_new_transform_variants_without_approval_pass(
    tmp_path: Path,
) -> None:
    plan = make_assessment_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="normalize_dates",
                params={"column": "created_at", "output_format": "%Y-%m-%d"},
            ),
            PlanTransformation(
                step_id="s2",
                operation="replace_values",
                params={"columns": ["status"], "old": "N/A", "new": "unknown"},
            ),
        )
    )

    _validator(tmp_path).validate(plan)


def test_read_only_plan_without_approval_passes(tmp_path: Path) -> None:
    plan = make_assessment_plan()

    _validator(tmp_path).validate(plan)


def test_assessment_with_write_operation_is_rejected(tmp_path: Path) -> None:
    plan = make_assessment_plan(
        source=PlanSource(operation="save_csv", params={"path": "output.csv"})
    )

    _assert_code(plan, "PLAN_UNSAFE_OPERATION", workspace=tmp_path)


def test_assessment_with_destructive_transformation_is_rejected(tmp_path: Path) -> None:
    plan = make_assessment_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="drop_duplicate_rows",
                params={},
            ),
        )
    )

    _assert_code(plan, "PLAN_UNSAFE_OPERATION", workspace=tmp_path)


def test_assessment_with_filter_rows_is_rejected(tmp_path: Path) -> None:
    plan = make_assessment_plan(
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="filter_rows",
                params={"column": "status", "operator": "is_not_null"},
            ),
        )
    )

    _assert_code(plan, "PLAN_UNSAFE_OPERATION", workspace=tmp_path)


def test_invalid_plan_version_is_rejected(tmp_path: Path) -> None:
    plan = make_plan()
    object.__setattr__(plan, "plan_version", "2.0")

    _assert_code(plan, "PLAN_INVALID_SCHEMA", workspace=tmp_path)


def test_invalid_on_error_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(on_error="ignore")

    _assert_code(plan, "PLAN_INVALID_SCHEMA", workspace=tmp_path)


def test_non_boolean_chunking_flag_is_rejected(tmp_path: Path) -> None:
    plan = make_plan()
    object.__setattr__(plan.chunking, "enabled", "yes")

    _assert_code(plan, "PLAN_INVALID_SCHEMA", workspace=tmp_path)


def test_invalid_operation_name_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(source=PlanSource(operation="read csv", params={}))

    _assert_code(plan, "PLAN_INVALID_SCHEMA", workspace=tmp_path)


def test_invalid_step_id_is_rejected(tmp_path: Path) -> None:
    plan = make_plan(
        transformations=(PlanTransformation(step_id="s 1", operation="trim_whitespace", params={}),)
    )

    _assert_code(plan, "PLAN_INVALID_SCHEMA", workspace=tmp_path)


def test_payload_schema_errors_are_reported(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "plan_version": "1.0",
        "mode": "pipeline",
        "run_id": "1729850000000-a1b2c3d4",
        "name": "test_plan",
        "description": "A test plan",
        "source": {"operation": "read_csv", "params": {"path": "input.csv"}},
        "transformations": [],
        "destination": {"operation": "save_csv", "params": {"path": "output.csv"}},
        "chunking": {"enabled": True, "size": 1000},
        "on_error": "fail_fast",
        "approval_required": True,
        "unexpected": True,
    }

    with pytest.raises(PlanValidationError) as caught:
        _validator(tmp_path).validate(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"
