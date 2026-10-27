import inspect
from dataclasses import replace
from typing import cast

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from application.ports.module_registry import ModuleRegistryPort
from domain.errors import RegistryError
from infrastructure.registry.catalog import MODULE_SPECS, ModuleSpec, build_snapshot
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.transformations.trim_whitespace import trim_whitespace


def _invalid_default(*, value: str = cast(str, 123)) -> pd.DataFrame:
    return pd.DataFrame({"value": [value]})


def _outside_path(*, value: str = "ok") -> pd.DataFrame:
    return pd.DataFrame({"value": [value]})


def test_registry_is_versioned_and_contains_the_approved_modules() -> None:
    snapshot = build_module_registry().snapshot()

    assert snapshot.version == "1.0.0"
    assert [module.name for module in snapshot.modules] == [
        "drop_duplicate_rows",
        "drop_empty_rows",
        "trim_whitespace",
        "standardize_column_names",
        "cast_column",
        "read_csv",
        "save_csv",
    ]
    assert {module.version for module in snapshot.modules} == {"1.0.0"}


def test_registry_metadata_matches_callable_signatures() -> None:
    snapshot = build_module_registry().snapshot()

    for module in snapshot.modules:
        spec = next(item for item in MODULE_SPECS if item.name == module.name)
        signature = inspect.signature(spec.function)

        assert tuple(item.name for item in module.inputs) == tuple(signature.parameters)
        assert module.module == spec.function.__module__
        assert module.function == spec.function.__name__
        assert module.output.type == "DataFrame"
        if module.name != "save_csv":
            assert module.idempotent
        if module.name != "save_csv":
            assert not module.side_effects
        assert module.examples
        if module.name in ["drop_duplicate_rows", "drop_empty_rows", "trim_whitespace", "standardize_column_names", "cast_column", "save_csv"]:
            assert [item.name for item in module.inputs if item.pipeline_input] == ["df"]
        elif module.name in ["read_csv"]:
            pass



        for item in module.inputs:
            parameter = signature.parameters[item.name]
            assert item.required == (parameter.default is inspect.Parameter.empty)


def test_registry_examples_only_use_caller_inputs() -> None:
    snapshot = build_module_registry().snapshot()

    for module in snapshot.modules:
        caller_inputs = {item.name for item in module.inputs if not item.pipeline_input}
        required = {
            item.name for item in module.inputs if item.required and not item.pipeline_input
        }
        for example in module.examples:
            assert set(example) <= caller_inputs
            assert required <= set(example)


def test_registry_satisfies_the_application_port() -> None:
    registry: ModuleRegistryPort = build_module_registry()

    assert registry.require("trim_whitespace").version == "1.0.0"
    registry.ensure_version("1.0.0")


def test_registry_resolves_only_allowlisted_callables() -> None:
    registry = build_module_registry()
    function = registry.function_for("trim_whitespace")
    df = pd.DataFrame({"name": [" Ada "]})

    result = function(df, columns=["name"])

    assert_frame_equal(result, trim_whitespace(df, columns=["name"]))
    assert function is trim_whitespace


def test_registry_returns_none_for_unknown_modules() -> None:
    registry = build_module_registry()

    assert registry.get("missing") is None

    with pytest.raises(RegistryError) as caught:
        registry.require("missing")

    assert caught.value.code == "REGISTRY_UNKNOWN_MODULE"
    assert caught.value.context == {"module": "missing"}


def test_registry_rejects_version_mismatches() -> None:
    registry = build_module_registry()

    with pytest.raises(RegistryError) as module:
        registry.get("trim_whitespace", version="0.9.0")
    with pytest.raises(RegistryError) as snapshot:
        registry.ensure_version("0.9.0")

    assert module.value.code == "REGISTRY_VERSION_MISMATCH"
    assert module.value.context == {"expected": "0.9.0", "current": "1.0.0"}
    assert snapshot.value.code == "REGISTRY_VERSION_MISMATCH"


def test_registry_builder_rejects_duplicate_modules() -> None:
    spec = MODULE_SPECS[0]

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec, spec))

    assert caught.value.code == "REGISTRY_DUPLICATE_MODULE"


def test_registry_builder_rejects_unknown_constraints() -> None:
    spec = replace(MODULE_SPECS[0], constraints={"missing": ("constraint",)})

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,))

    assert caught.value.code == "REGISTRY_INVALID_CONSTRAINT"
    assert caught.value.context == {"module": spec.name, "inputs": ["missing"]}


def test_registry_builder_rejects_name_drift() -> None:
    spec = replace(MODULE_SPECS[0], name="renamed_module")

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,))

    assert caught.value.code == "REGISTRY_SIGNATURE_MISMATCH"


def test_registry_builder_rejects_missing_required_example_inputs() -> None:
    spec = next(item for item in MODULE_SPECS if item.name == "cast_column")
    spec = replace(spec, examples=({},))

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,))

    assert caught.value.code == "REGISTRY_INVALID_EXAMPLE"
    assert caught.value.context == {
        "module": "cast_column",
        "example_index": 0,
        "inputs": ["column", "target_type"],
    }


def test_registry_builder_rejects_wrong_example_types_and_enums() -> None:
    spec = next(item for item in MODULE_SPECS if item.name == "cast_column")

    with pytest.raises(RegistryError) as wrong_type:
        build_snapshot((replace(spec, examples=({"column": 1, "target_type": "integer"},)),))
    with pytest.raises(RegistryError) as wrong_enum:
        build_snapshot((replace(spec, examples=({"column": "a", "target_type": "date"},)),))

    assert wrong_type.value.code == "REGISTRY_INVALID_EXAMPLE"
    assert wrong_enum.value.code == "REGISTRY_INVALID_EXAMPLE"


def test_registry_builder_rejects_pipeline_inputs_in_examples() -> None:
    spec = next(item for item in MODULE_SPECS if item.name == "cast_column")
    spec = replace(
        spec,
        examples=({"df": object(), "column": "amount", "target_type": "float"},),
    )

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,))

    assert caught.value.code == "REGISTRY_INVALID_EXAMPLE"
    assert caught.value.context["inputs"] == ["df"]


def test_registry_builder_rejects_missing_dependencies() -> None:
    spec = replace(
        MODULE_SPECS[0],
        dependencies=("dependency_that_does_not_exist",),
    )

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,))

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
        function=_invalid_default,
        description="Fake module.",
        constraints={},
        examples=(),
        supports_chunking=True,
        idempotent=True,
        security_notes="Test only.",
    )

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,))

    assert caught.value.code == "REGISTRY_INVALID_DEFAULT"
    assert caught.value.context == {"module": "_invalid_default", "input": "value"}


def test_registry_builder_rejects_unapproved_module_paths() -> None:
    _outside_path.__module__ = "os.path"
    spec = ModuleSpec(
        name="_outside_path",
        version="1.0.0",
        function=_outside_path,
        description="Fake module.",
        constraints={},
        examples=(),
        supports_chunking=True,
        idempotent=True,
        security_notes="Test only.",
    )

    with pytest.raises(RegistryError) as caught:
        build_snapshot((spec,))

    assert caught.value.code == "REGISTRY_INVALID_MODULE_PATH"
    assert caught.value.context == {"module": "_outside_path", "path": "os.path"}
