import inspect
from collections.abc import Callable
from dataclasses import replace
from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from application.ports.module_registry import ModuleRegistryPort
from application.registry.specs import MODULE_SPECS, ModuleSpec
from domain.errors import RegistryError
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.functions import build_snapshot
from infrastructure.registry.module_registry import ModuleRegistry, build_module_registry
from infrastructure.transformations.trim_whitespace import trim_whitespace


def _registry() -> ModuleRegistry:
    return build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)


def _functions_for(*specs: ModuleSpec) -> dict[str, Callable[..., pd.DataFrame]]:
    return {spec.name: MODULE_FUNCTIONS[spec.name] for spec in specs}


def _invalid_default(*, value: str = cast(str, 123)) -> pd.DataFrame:
    return pd.DataFrame({"value": [value]})


def _outside_path(*, value: str = "ok") -> pd.DataFrame:
    return pd.DataFrame({"value": [value]})


def test_registry_is_versioned_and_contains_the_approved_modules() -> None:
    snapshot = _registry().snapshot()

    assert snapshot.version == "1.0.0"
    assert [module.name for module in snapshot.modules] == [
        "drop_duplicate_rows",
        "drop_empty_rows",
        "trim_whitespace",
        "standardize_column_names",
        "cast_column",
        "filter_rows",
        "fill_missing_values",
        "normalize_dates",
        "change_text_case",
        "replace_values",
        "read_csv",
        "read_json",
        "read_jsonl",
        "read_parquet",
        "save_csv",
        "save_json",
        "save_jsonl",
        "save_parquet",
    ]
    assert {module.version for module in snapshot.modules} == {"1.0.0"}


def test_registry_metadata_matches_callable_signatures() -> None:
    snapshot = _registry().snapshot()

    for module in snapshot.modules:
        spec = next(item for item in MODULE_SPECS if item.name == module.name)
        function = MODULE_FUNCTIONS[spec.name]
        signature = inspect.signature(function)

        assert tuple(item.name for item in module.inputs) == tuple(signature.parameters)
        assert module.module == function.__module__
        assert module.function == function.__name__
        assert module.output.type == "DataFrame"
        if module.name in {"save_csv", "save_json", "save_jsonl", "save_parquet"}:
            assert not module.idempotent
            assert module.side_effects
        else:
            assert module.idempotent
            assert not module.side_effects
        assert module.examples
        if module.name in [
            "drop_duplicate_rows",
            "drop_empty_rows",
            "trim_whitespace",
            "standardize_column_names",
            "cast_column",
            "filter_rows",
            "fill_missing_values",
            "normalize_dates",
            "change_text_case",
            "replace_values",
            "save_csv",
            "save_json",
            "save_jsonl",
            "save_parquet",
        ]:
            assert [item.name for item in module.inputs if item.pipeline_input] == ["df"]
        elif module.name in ["read_csv", "read_json", "read_jsonl", "read_parquet"]:
            pass

        for item in module.inputs:
            parameter = signature.parameters[item.name]
            assert item.required == (parameter.default is inspect.Parameter.empty)


def test_registry_examples_only_use_caller_inputs() -> None:
    snapshot = _registry().snapshot()

    for module in snapshot.modules:
        caller_inputs = {item.name for item in module.inputs if not item.pipeline_input}
        required = {
            item.name for item in module.inputs if item.required and not item.pipeline_input
        }
        for example in module.examples:
            assert set(example) <= caller_inputs
            assert required <= set(example)


def test_registry_satisfies_the_application_port() -> None:
    registry: ModuleRegistryPort = _registry()

    assert registry.require("trim_whitespace").version == "1.0.0"


def test_registry_resolves_only_allowlisted_callables() -> None:
    registry = _registry()
    function = registry.function_for("trim_whitespace")
    df = pd.DataFrame({"name": [" Ada "]})

    result = function(df, columns=["name"])

    assert_frame_equal(result, trim_whitespace(df, columns=["name"]))
    assert function is trim_whitespace


def test_registry_returns_none_for_unknown_modules() -> None:
    registry = _registry()

    assert registry.get("missing") is None

    with pytest.raises(RegistryError) as caught:
        registry.require("missing")

    assert caught.value.code == "REGISTRY_UNKNOWN_MODULE"
    assert caught.value.context == {"module": "missing"}


def test_registry_rejects_version_mismatches() -> None:
    registry = _registry()

    with pytest.raises(RegistryError) as caught:
        registry.get("trim_whitespace", version="0.9.0")

    assert caught.value.code == "REGISTRY_VERSION_MISMATCH"
    assert caught.value.context == {"expected": "0.9.0", "current": "1.0.0"}


def test_registry_builder_rejects_duplicate_modules() -> None:
    spec = MODULE_SPECS[0]

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec, spec), _functions_for(spec))

    assert caught.value.code == "REGISTRY_DUPLICATE_MODULE"


def test_registry_builder_rejects_unknown_constraints() -> None:
    spec = replace(MODULE_SPECS[0], constraints={"missing": ()})

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,), _functions_for(spec))

    assert caught.value.code == "REGISTRY_INVALID_CONSTRAINT"
    assert caught.value.context == {"module": spec.name, "inputs": ["missing"]}


def test_registry_builder_rejects_name_drift() -> None:
    spec = replace(MODULE_SPECS[0], name="renamed_module")

    with pytest.raises(RegistryError) as caught:
        build_snapshot(
            (spec,),
            {"renamed_module": MODULE_FUNCTIONS["drop_duplicate_rows"]},
        )

    assert caught.value.code == "REGISTRY_SIGNATURE_MISMATCH"


def test_registry_builder_rejects_missing_required_example_inputs() -> None:
    spec = next(item for item in MODULE_SPECS if item.name == "cast_column")
    spec = replace(spec, examples=({},))

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,), _functions_for(spec))

    assert caught.value.code == "REGISTRY_INVALID_EXAMPLE"
    assert caught.value.context == {
        "module": "cast_column",
        "example_index": 0,
        "inputs": ["column", "target_type"],
    }


def test_registry_builder_rejects_wrong_example_types_and_enums() -> None:
    spec = next(item for item in MODULE_SPECS if item.name == "cast_column")

    wrong_type_spec = replace(spec, examples=({"column": 1, "target_type": "integer"},))
    wrong_enum_spec = replace(spec, examples=({"column": "a", "target_type": "date"},))

    with pytest.raises(RegistryError) as wrong_type:
        build_snapshot((wrong_type_spec,), _functions_for(wrong_type_spec))
    with pytest.raises(RegistryError) as wrong_enum:
        build_snapshot((wrong_enum_spec,), _functions_for(wrong_enum_spec))

    assert wrong_type.value.code == "REGISTRY_INVALID_EXAMPLE"
    assert wrong_enum.value.code == "REGISTRY_INVALID_EXAMPLE"


def test_registry_builder_rejects_pipeline_inputs_in_examples() -> None:
    spec = next(item for item in MODULE_SPECS if item.name == "cast_column")
    spec = replace(
        spec,
        examples=({"df": object(), "column": "amount", "target_type": "float"},),
    )

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,), _functions_for(spec))

    assert caught.value.code == "REGISTRY_INVALID_EXAMPLE"
    assert caught.value.context["inputs"] == ["df"]


def test_registry_builder_rejects_missing_dependencies() -> None:
    spec = replace(
        MODULE_SPECS[0],
        dependencies=("dependency_that_does_not_exist",),
    )

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,), _functions_for(spec))

    assert caught.value.code == "REGISTRY_MISSING_DEPENDENCY"
    assert caught.value.context == {
        "module": "drop_duplicate_rows",
        "dependency": "dependency_that_does_not_exist",
    }


def test_registry_builder_rejects_invalid_defaults() -> None:
    _invalid_default.__module__ = "infrastructure.transformations.fake"
    spec = ModuleSpec(
        name="_invalid_default",
        version="1.0.0",
        description="Fake module.",
        constraints={},
        examples=(),
        supports_chunking=True,
        idempotent=True,
        security_notes="Test only.",
    )

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,), {"_invalid_default": _invalid_default})

    assert caught.value.code == "REGISTRY_INVALID_DEFAULT"
    assert caught.value.context == {"module": "_invalid_default", "input": "value"}


def test_registry_builder_requires_a_callable_for_every_spec() -> None:
    spec = MODULE_SPECS[0]

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,), {})

    assert caught.value.code == "REGISTRY_MISSING_FUNCTION"
    assert caught.value.context == {"modules": [spec.name]}


def test_registry_builder_rejects_unbound_callables() -> None:
    spec = MODULE_SPECS[0]

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,), MODULE_FUNCTIONS)

    assert caught.value.code == "REGISTRY_UNKNOWN_FUNCTION"
    assert caught.value.context == {
        "modules": sorted(set(MODULE_FUNCTIONS) - {spec.name}),
    }


def test_registry_builder_rejects_unapproved_module_paths() -> None:
    _outside_path.__module__ = "os.path"
    spec = ModuleSpec(
        name="_outside_path",
        version="1.0.0",
        description="Fake module.",
        constraints={},
        examples=(),
        supports_chunking=True,
        idempotent=True,
        security_notes="Test only.",
    )

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,), {"_outside_path": _outside_path})

    assert caught.value.code == "REGISTRY_INVALID_MODULE_PATH"
    assert caught.value.context == {"module": "_outside_path", "path": "os.path"}
