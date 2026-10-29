"""Unit tests for the registry-derived draft JSON schema."""

from __future__ import annotations

from typing import Any

import pytest

from application.planning.schema import MAX_DRAFT_TRANSFORMATIONS, build_plan_draft_schema
from application.registry.specs import MODULE_SPECS
from domain.entities.registry import RegistrySnapshot
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry

SNAPSHOT = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS).snapshot()


def _schema() -> dict[str, Any]:
    return build_plan_draft_schema(SNAPSHOT)


def _operations(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    transformations = schema["properties"]["transformations"]
    return {
        item["properties"]["operation"]["enum"][0]: item
        for item in transformations["items"]["oneOf"]
    }


def test_schema_contains_only_transformations() -> None:
    operations = _operations(_schema())

    expected = {
        module.name
        for module in SNAPSHOT.modules
        if any(item.pipeline_input for item in module.inputs) and not module.side_effects
    }
    assert set(operations) == expected
    assert "read_csv" not in operations
    assert "save_csv" not in operations


def test_schema_is_strict_and_mentions_every_required_field() -> None:
    schema = _schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "name",
        "description",
        "transformations",
        "questions",
        "missing_inputs",
    }
    assert schema["properties"]["transformations"]["maxItems"] == MAX_DRAFT_TRANSFORMATIONS
    assert schema["properties"]["transformations"]["items"]["oneOf"]
    assert schema["properties"]["questions"]["items"]["maxLength"] == 500


def test_operation_parameters_have_exact_names_and_enums() -> None:
    operations = _operations(_schema())

    trim = operations["trim_whitespace"]["properties"]["params"]
    assert set(trim["properties"]) == {"columns", "policy"}
    assert trim["properties"]["policy"] == {
        "type": "string",
        "enum": ["both", "leading", "trailing"],
    }
    column_branches = trim["properties"]["columns"]["anyOf"]
    assert any(branch.get("type") == "array" for branch in column_branches)
    assert any(branch.get("type") == "null" for branch in column_branches)
    assert trim["required"] == []
    assert trim["additionalProperties"] is False

    cast = operations["cast_column"]["properties"]["params"]
    assert cast["required"] == ["column", "target_type"]
    assert cast["properties"]["target_type"] == {
        "type": "string",
        "enum": ["string", "integer", "float"],
    }

    duplicate = operations["drop_duplicate_rows"]["properties"]["params"]
    assert duplicate["required"] == []
    assert duplicate["properties"]["keep"]["enum"] == ["first", "last"]


def test_union_parameter_uses_anyof_not_oneof() -> None:
    filter_params = _operations(_schema())["filter_rows"]["properties"]["params"]

    assert "anyOf" in filter_params["properties"]["value"]
    assert "oneOf" not in filter_params["properties"]["value"]


def test_schema_rejects_empty_snapshot() -> None:
    with pytest.raises(ValueError, match="transformation"):
        build_plan_draft_schema(RegistrySnapshot(version="1.0.0", modules=()))
