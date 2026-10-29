"""Unit tests for the strict model draft parser."""

from __future__ import annotations

import pytest

from domain.errors import PlanSynthesisError
from infrastructure.planning.draft_schema import parse_plan_draft


def _payload() -> dict[str, object]:
    return {
        "name": "clean_orders",
        "description": "Remove duplicates and trim values.",
        "transformations": [
            {
                "operation": "drop_duplicate_rows",
                "params": {"subset": [], "keep": "first"},
            },
            {
                "operation": "trim_whitespace",
                "params": {"columns": [], "policy": "both"},
            },
        ],
        "questions": [],
        "missing_inputs": [],
    }


def test_valid_draft_assigns_step_ids_and_removes_empty_lists() -> None:
    draft = parse_plan_draft(_payload())

    assert draft.name == "clean_orders"
    assert [step.step_id for step in draft.transformations] == ["s1", "s2"]
    assert draft.transformations[0].params == {"keep": "first"}
    assert draft.transformations[1].params == {"policy": "both"}
    assert not draft.needs_input


def test_draft_questions_are_preserved() -> None:
    payload = _payload()
    payload["questions"] = ["Which column should be trimmed?"]
    payload["missing_inputs"] = ["column"]

    draft = parse_plan_draft(payload)

    assert draft.needs_input
    assert draft.questions == ("Which column should be trimmed?",)
    assert draft.missing_inputs == ("column",)


@pytest.mark.parametrize(
    "payload",
    [
        {**_payload(), "extra": True},
        {**_payload(), "name": "   "},
        {**_payload(), "questions": ["  "]},
        {**_payload(), "transformations": [{"operation": "drop table", "params": {}}]},
        {
            **_payload(),
            "transformations": [{"operation": "drop_duplicate_rows", "params": {}}] * 21,
        },
    ],
)
def test_invalid_draft_raises_synthesis_error(payload: dict[str, object]) -> None:
    with pytest.raises(PlanSynthesisError) as caught:
        parse_plan_draft(payload)

    assert caught.value.code == "PLAN_SYNTHESIS_INVALID"
    assert caught.value.context["errors"]
