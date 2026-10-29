"""Golden plan-shape cases for natural-language intake.

These cases use a deterministic synthesizer so they test binding, validation,
and plan shape without depending on a model runtime.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from application.planning.intake import NaturalLanguagePlanIntake
from application.planning.models import SourceSchema
from application.ports.plan_synthesizer import ConversationTurn
from domain.entities.plan import PlanTransformation
from domain.entities.plan_draft import PlanDraft
from domain.entities.run import PlanRequest
from domain.errors import PlanValidationError
from infrastructure.validation.plan_parser import PydanticPlanParser


class _FakeSynthesizer:
    def __init__(self, draft: PlanDraft) -> None:
        self.draft = draft

    def synthesize(
        self,
        request: PlanRequest,
        *,
        history: Sequence[ConversationTurn] = (),
        previous_error: PlanValidationError | None = None,
        source_schema: SourceSchema | None = None,
    ) -> PlanDraft:
        del request, history, previous_error, source_schema
        return self.draft


def _draft(*operations: str) -> PlanDraft:
    return PlanDraft(
        name="golden_plan",
        description="Golden plan",
        transformations=tuple(
            PlanTransformation(step_id=f"s{index}", operation=operation, params=_params(operation))
            for index, operation in enumerate(operations, start=1)
        ),
    )


def _params(operation: str) -> dict[str, object]:
    if operation == "cast_column":
        return {"column": "amount", "target_type": "float"}
    if operation == "filter_rows":
        return {"column": "status", "operator": "equals", "value": "active"}
    if operation == "normalize_dates":
        return {"column": "created_at", "output_format": "%Y-%m-%d"}
    if operation == "replace_values":
        return {"columns": ["status"], "old": "N/A", "new": None}
    if operation == "trim_whitespace":
        return {"policy": "both"}
    return {}


def _request(message: str) -> PlanRequest:
    return PlanRequest(
        run_id="run-golden",
        thread_id="thread-golden",
        message=message,
        source="input.csv",
        destination="output.json",
    )


@pytest.mark.parametrize(
    ("message", "operations"),
    [
        (
            "Remove duplicate rows and trim whitespace",
            ("drop_duplicate_rows", "trim_whitespace"),
        ),
        (
            "Standardize the column names and trim whitespace",
            ("standardize_column_names", "trim_whitespace"),
        ),
        ("Cast amount to float", ("cast_column",)),
        ("Keep only active status rows", ("filter_rows",)),
        ("Normalize created_at to %Y-%m-%d", ("normalize_dates",)),
        ("Replace N/A in status with null", ("replace_values",)),
    ],
)
def test_golden_plan_shape(message: str, operations: tuple[str, ...]) -> None:
    intake = NaturalLanguagePlanIntake(
        synthesizer=_FakeSynthesizer(_draft(*operations)),
        parser=PydanticPlanParser(),
    )

    result = intake.request(_request(message), attempt=1)

    assert result.plan is not None
    assert tuple(step.operation for step in result.plan.transformations) == operations
    assert result.plan.source is not None
    assert result.plan.source.operation == "read_csv"
    assert result.plan.destination is not None
    assert result.plan.destination.operation == "save_json"
    assert result.plan.approval_required is True
