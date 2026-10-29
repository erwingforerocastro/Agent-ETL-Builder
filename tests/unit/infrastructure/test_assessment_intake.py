"""Unit tests for the assessment plan intake adapter."""

from __future__ import annotations

from typing import cast

from application.assessment.assess_source import AssessSourceUseCase
from domain.entities.assessment import AssessmentReport, DraftPlan
from domain.entities.plan import PlanChunking
from domain.entities.run import PlanRequest
from domain.errors import IngestionError
from infrastructure.assessment.intake import AssessmentPlanIntake


class _Assessor:
    def __init__(
        self,
        *,
        report: AssessmentReport | None = None,
        error: IngestionError | None = None,
    ) -> None:
        self._report = report
        self._error = error
        self.calls: list[tuple[str, str]] = []

    def execute(self, *, run_id: str, reference: str) -> AssessmentReport:
        self.calls.append((run_id, reference))
        if self._error is not None:
            raise self._error
        assert self._report is not None
        return self._report


def _report() -> AssessmentReport:
    return AssessmentReport(
        assessment_id="asm_run-1",
        run_id="run-1",
        source_id="src_abc",
        source_type="csv",
        row_count=1,
        column_count=1,
        content_hash="sha256:source",
        schema_hash="sha256:schema",
        issues=(),
        assumptions=("The source was read fully.",),
        missing_inputs=("destination",),
        draft_plan=DraftPlan(
            name="assess_src",
            description="Assess the source",
            source_operation="read_csv",
            source_params={"path": "input.csv"},
            transformations=(),
            chunking=PlanChunking(enabled=True, size=1000),
        ),
        chunk_count=1,
    )


def _request(*, source: str | None = "input.csv", mode: str = "pipeline") -> PlanRequest:
    return PlanRequest(
        run_id="run-1",
        thread_id="thread-1",
        message="Assess the source",
        source=source,
        mode=mode,
    )


def _intake(assessor: _Assessor) -> AssessmentPlanIntake:
    return AssessmentPlanIntake(cast(AssessSourceUseCase, assessor))


def test_missing_source_asks_for_it_without_assessing() -> None:
    assessor = _Assessor(report=_report())

    result = _intake(assessor).request(_request(source=None), attempt=1)

    assert result.assessment is None
    assert result.missing_inputs == ("source",)
    assert assessor.calls == []


def test_unreadable_source_becomes_a_clarification() -> None:
    assessor = _Assessor(
        error=IngestionError(
            code="SOURCE_NOT_FOUND",
            message="Source file was not found",
            module="test",
        )
    )

    result = _intake(assessor).request(_request(), attempt=1)

    assert result.assessment is None
    assert result.missing_inputs == ("source",)
    assert result.questions == ("The source could not be assessed (SOURCE_NOT_FOUND).",)


def test_pipeline_assessment_requests_a_destination() -> None:
    report = _report()
    assessor = _Assessor(report=report)

    result = _intake(assessor).request(_request(mode="pipeline"), attempt=1)

    assert result.assessment is report
    assert result.missing_inputs == ("destination",)
    assert result.questions == (
        "Review the assessment and confirm a destination for the draft plan.",
    )
    assert assessor.calls == [("run-1", "input.csv")]


def test_assessment_only_mode_does_not_request_a_destination() -> None:
    report = _report()
    assessor = _Assessor(report=report)

    result = _intake(assessor).request(_request(mode="assessment"), attempt=1)

    assert result.assessment is report
    assert result.missing_inputs == ()
    assert result.questions == (
        "Assessment complete. Submit a structured pipeline plan to write output.",
    )
