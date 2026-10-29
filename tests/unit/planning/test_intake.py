"""Unit tests for natural-language plan intake."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from application.planning.intake import NaturalLanguagePlanIntake
from application.planning.models import SourceSchema
from application.ports.plan_synthesizer import ConversationTurn
from application.ports.source_schema import SourceSchemaPort
from application.registry.specs import MODULE_SPECS
from domain.entities.plan import PlanTransformation
from domain.entities.plan_draft import PlanDraft
from domain.entities.run import PlanRequest
from domain.errors import IngestionError, PlanValidationError
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.validation.plan_parser import PydanticPlanParser

SNAPSHOT = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS).snapshot()


class _FakeSynthesizer:
    def __init__(self, drafts: Sequence[PlanDraft]) -> None:
        self._drafts = list(drafts)
        self.calls: list[
            tuple[
                PlanRequest,
                tuple[ConversationTurn, ...],
                PlanValidationError | None,
                SourceSchema | None,
            ]
        ] = []

    def synthesize(
        self,
        request: PlanRequest,
        *,
        history: Sequence[ConversationTurn] = (),
        previous_error: PlanValidationError | None = None,
        source_schema: SourceSchema | None = None,
    ) -> PlanDraft:
        self.calls.append((request, tuple(history), previous_error, source_schema))
        if not self._drafts:
            raise AssertionError("no draft configured")
        return self._drafts.pop(0)


def _draft(**overrides: object) -> PlanDraft:
    values: dict[str, object] = {
        "name": "clean_orders",
        "description": "Remove duplicates.",
        "transformations": (
            PlanTransformation(
                step_id="s1",
                operation="drop_duplicate_rows",
                params={},
            ),
        ),
    }
    values.update(overrides)
    return PlanDraft(**values)  # type: ignore[arg-type]


class _SchemaProbe:
    def __init__(
        self,
        schema: SourceSchema | None = None,
        error: Exception | None = None,
    ) -> None:
        self.schema = schema or SourceSchema(columns=("name",), dtypes=("string",))
        self.error = error
        self.calls: list[str] = []

    def inspect(self, source: str) -> SourceSchema:
        self.calls.append(source)
        if self.error is not None:
            raise self.error
        return self.schema


def _intake(
    *drafts: PlanDraft,
    schema_probe: SourceSchemaPort | None = None,
) -> tuple[NaturalLanguagePlanIntake, _FakeSynthesizer]:
    synthesizer = _FakeSynthesizer(drafts)
    return (
        NaturalLanguagePlanIntake(
            synthesizer=synthesizer,
            parser=PydanticPlanParser(),
            schema_probe=schema_probe,
        ),
        synthesizer,
    )


def _request(**overrides: object) -> PlanRequest:
    values: dict[str, object] = {
        "run_id": "run-1",
        "thread_id": "thread-1",
        "message": "Remove duplicates",
        "source": "input.csv",
        "destination": "output.json",
    }
    values.update(overrides)
    return PlanRequest(**values)  # type: ignore[arg-type]


def test_missing_source_and_destination_are_asked_without_model_call() -> None:
    intake, synthesizer = _intake()

    result = intake.request(
        _request(source=None, destination=None),
        attempt=1,
    )

    assert result.plan is None
    assert result.missing_inputs == ("source", "destination")
    assert len(result.questions) == 2
    assert synthesizer.calls == []


def test_unsupported_source_and_destination_are_asked() -> None:
    intake, synthesizer = _intake()

    result = intake.request(
        _request(source="input.txt", destination="output.txt"),
        attempt=1,
    )

    assert result.plan is None
    assert result.missing_inputs == ("source", "destination")
    assert all("not supported" in question for question in result.questions)
    assert synthesizer.calls == []


def test_same_source_and_destination_is_rejected() -> None:
    intake, synthesizer = _intake()

    result = intake.request(
        _request(destination="./input.csv"),
        attempt=1,
    )

    assert result.plan is None
    assert result.missing_inputs == ("destination",)
    assert "different workspace path" in result.questions[0]
    assert synthesizer.calls == []


def test_valid_draft_is_bound_to_source_and_destination() -> None:
    intake, synthesizer = _intake(_draft())

    result = intake.request(_request(), attempt=1)

    assert result.plan is not None
    plan = result.plan
    assert plan.source is not None
    assert plan.source.operation == "read_csv"
    assert plan.source.params == {"path": "input.csv"}
    assert plan.destination is not None
    assert plan.destination.operation == "save_json"
    assert plan.destination.params == {"path": "output.json"}
    assert [step.step_id for step in plan.transformations] == ["s1"]
    assert plan.approval_required is True
    assert plan.chunking.enabled is False
    assert len(synthesizer.calls) == 1
    assert synthesizer.calls[0][1] == (("user", "Remove duplicates"),)


def test_source_schema_is_passed_to_the_synthesizer() -> None:
    probe = _SchemaProbe()
    intake, synthesizer = _intake(_draft(), schema_probe=probe)

    result = intake.request(_request(), attempt=1)

    assert result.plan is not None
    assert probe.calls == ["input.csv"]
    assert synthesizer.calls[0][3] == probe.schema


def test_source_schema_is_cached_between_attempts() -> None:
    probe = _SchemaProbe()
    intake, synthesizer = _intake(_draft(), _draft(), schema_probe=probe)
    intake.request(_request(), attempt=1)

    intake.request(
        _request(),
        attempt=2,
        previous_error=PlanValidationError(
            code="PLAN_INVALID_ARGUMENT",
            message="repair",
            module="test",
        ),
    )

    assert probe.calls == ["input.csv"]
    assert synthesizer.calls[1][3] == probe.schema


def test_source_inspection_failure_becomes_a_clarification() -> None:
    probe = _SchemaProbe(
        error=IngestionError(
            code="SOURCE_NOT_FOUND",
            message="Source file was not found",
            module="test",
        )
    )
    intake, synthesizer = _intake(_draft(), schema_probe=probe)

    result = intake.request(_request(), attempt=1)

    assert result.plan is None
    assert "could not inspect the source" in result.questions[0]
    assert result.missing_inputs == ("source",)
    assert synthesizer.calls == []


def test_source_and_destination_are_retained_across_clarification() -> None:
    intake, synthesizer = _intake(_draft())

    first = intake.request(
        PlanRequest(
            run_id="run-1",
            thread_id="thread-1",
            message="Remove duplicates",
            source="input.csv",
        ),
        attempt=1,
    )
    second = intake.request(
        PlanRequest(
            run_id="run-1",
            thread_id="thread-1",
            message="Use output.json",
            destination="output.json",
        ),
        attempt=2,
    )

    assert first.plan is None
    assert second.plan is not None
    assert second.plan.source is not None
    assert second.plan.source.params == {"path": "input.csv"}
    assert len(synthesizer.calls) == 1
    assert synthesizer.calls[0][1][-1] == ("user", "Use output.json")
    assert any(role == "assistant" for role, _ in synthesizer.calls[0][1])


def test_model_questions_become_a_clarification() -> None:
    intake, _ = _intake(
        _draft(
            transformations=(),
            questions=("Which column should be trimmed?",),
            missing_inputs=("column",),
        )
    )

    result = intake.request(_request(), attempt=1)

    assert result.plan is None
    assert result.questions == ("Which column should be trimmed?",)
    assert result.missing_inputs == ("column",)


def test_assessment_mode_asks_for_an_explicit_source() -> None:
    intake, synthesizer = _intake()

    result = intake.request(_request(mode="assessment"), attempt=1)

    assert result.plan is None
    assert result.missing_inputs == ("source",)
    assert "Assessment requests need an explicit source" in result.questions[0]
    assert synthesizer.calls == []


def test_parser_validation_error_is_propagated_for_repair() -> None:
    intake, _ = _intake(_draft(name="x" * 300))

    with pytest.raises(PlanValidationError) as caught:
        intake.request(_request(), attempt=1)

    assert caught.value.code == "PLAN_INVALID_SCHEMA"
