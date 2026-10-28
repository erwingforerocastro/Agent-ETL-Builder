"""Unit tests for the strict plan schema."""

from collections.abc import Mapping
from typing import cast

import pytest

from infrastructure.validation.errors import PlanValidationError
from infrastructure.validation.plan_schema import (
    ExecutionPlanSchema,
    PlanSchema,
    parse_plan,
)


def _payload() -> dict[str, object]:
    return {
        "plan_version": "1.0",
        "mode": "pipeline",
        "run_id": "1729850000000-a1b2c3d4",
        "name": "normalize_orders",
        "description": "Read orders and normalize values",
        "source": {"operation": "read_csv", "params": {"path": "orders.csv"}},
        "transformations": [
            {
                "step_id": "s1",
                "operation": "trim_whitespace",
                "params": {"columns": ["customer_name"]},
            }
        ],
        "destination": {"operation": "save_csv", "params": {"path": "clean.csv"}},
        "chunking": {"enabled": True, "size": 1000},
        "on_error": "fail_fast",
        "approval_required": True,
    }


def test_schema_alias_is_exported() -> None:
    assert PlanSchema is ExecutionPlanSchema


def test_parse_plan_returns_domain_entities() -> None:
    plan = parse_plan(_payload())

    assert plan.plan_version == "1.0"
    assert plan.mode == "pipeline"
    assert plan.source is not None
    assert plan.source.operation == "read_csv"
    assert plan.source.params == {"path": "orders.csv"}
    assert len(plan.transformations) == 1
    assert plan.transformations[0].step_id == "s1"
    assert plan.destination is not None
    assert plan.destination.operation == "save_csv"
    assert plan.chunking.enabled is True
    assert plan.chunking.size == 1000
    assert plan.approval_required is True


def test_parse_plan_accepts_assessment_without_destination() -> None:
    payload = _payload()
    payload["mode"] = "assessment"
    payload["destination"] = None
    payload["approval_required"] = False

    plan = parse_plan(payload)

    assert plan.mode == "assessment"
    assert plan.destination is None


def test_schema_rejects_unknown_top_level_fields() -> None:
    payload = _payload()
    payload["unexpected"] = "value"

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_unknown_nested_fields() -> None:
    payload = _payload()
    source = cast(dict[str, object], payload["source"])
    source["unexpected"] = "value"

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_missing_required_fields() -> None:
    payload = _payload()
    del payload["chunking"]

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_wrong_types() -> None:
    payload = _payload()
    payload["chunking"] = {"enabled": "yes", "size": "1000"}

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_invalid_operation_and_step_id() -> None:
    invalid_operation = _payload()
    source = cast(dict[str, object], invalid_operation["source"])
    source["operation"] = "read csv"

    invalid_step = _payload()
    transformations = cast(list[dict[str, object]], invalid_step["transformations"])
    transformations[0]["step_id"] = "s 1"

    for payload in (invalid_operation, invalid_step):
        with pytest.raises(PlanValidationError) as caught:
            parse_plan(payload)
        assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_assessment_with_destination() -> None:
    payload = _payload()
    payload["mode"] = "assessment"

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_pipeline_without_destination() -> None:
    payload = _payload()
    payload["destination"] = None

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_duplicate_step_ids() -> None:
    payload = _payload()
    transformations = cast(list[dict[str, object]], payload["transformations"])
    transformations.append(dict(transformations[0]))

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


@pytest.mark.parametrize(
    "value",
    [
        {"nested": {1, 2}},
        float("nan"),
        "text\x00value",
    ],
)
def test_schema_rejects_non_json_values(value: object) -> None:
    payload = _payload()
    source = cast(dict[str, object], payload["source"])
    source["params"] = {"path": value}

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_non_string_param_keys() -> None:
    payload = _payload()
    source = cast(dict[str, object], payload["source"])
    source["params"] = {1: "value"}

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_rejects_excessive_nesting() -> None:
    nested: dict[str, object] = {}
    current = nested
    for _ in range(12):
        child: dict[str, object] = {}
        current["child"] = child
        current = child

    payload = _payload()
    source = cast(dict[str, object], payload["source"])
    source["params"] = {"path": nested}

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"


def test_schema_error_does_not_echo_secret_input() -> None:
    payload = _payload()
    payload["name"] = "another-secret"
    payload["chunking"] = {"enabled": True, "size": "secret-value"}

    with pytest.raises(PlanValidationError) as caught:
        parse_plan(payload)

    serialized = str(caught.value) + str(caught.value.context)
    assert "secret-value" not in serialized
    assert "another-secret" not in serialized


def test_parse_plan_rejects_non_mapping_payload() -> None:
    with pytest.raises(PlanValidationError):
        parse_plan(cast(Mapping[str, object], []))
