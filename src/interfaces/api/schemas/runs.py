"""Run API request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from application.logging.redaction import redact_mapping
from application.ports.run_log import RunLogEntry
from application.use_cases.execution_result import PlanExecutionResult
from application.use_cases.run_outcome import RunOutcome
from domain.entities.assessment import AssessmentReport
from domain.entities.plan import ExecutionPlan
from domain.entities.run import Run, RunStatus
from domain.errors import EtlError

NextAction = Literal["provide_plan", "clarify", "confirm", "approve", "wait", "none"]


class RunCreateRequest(BaseModel):
    """Create a run from a message and/or structured plan."""

    model_config = ConfigDict(extra="forbid")

    message: str | None = Field(default=None, max_length=10_000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    mode: Literal["pipeline", "assessment"] | None = None
    run_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    source: str | None = Field(default=None, max_length=2_000)
    destination: str | None = Field(default=None, max_length=2_000)
    plan: dict[str, Any] | None = None

    @field_validator("message", "thread_id", "run_id", "source", "destination")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("plan")
    @classmethod
    def _reject_empty_plan(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and not value:
            raise ValueError("plan must not be empty; omit plan to use natural-language planning")
        return value

    @model_validator(mode="after")
    def _require_message_or_plan(self) -> RunCreateRequest:
        if self.message is None and self.plan is None:
            raise ValueError("message or plan is required")
        return self


class RunApprovalRequest(BaseModel):
    """Approval or rejection decision for a pending run."""

    model_config = ConfigDict(extra="forbid")

    approved: bool


class RunConfirmRequest(BaseModel):
    """Destination supplied when confirming an assessment draft."""

    model_config = ConfigDict(extra="forbid")

    destination: str = Field(min_length=1, max_length=2_000)

    @field_validator("destination")
    @classmethod
    def _strip_destination(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("destination must not be blank")
        return stripped


class RunMessageRequest(BaseModel):
    """Follow-up message for a run waiting on clarification."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=10_000)
    source: str | None = Field(default=None, max_length=2_000)
    destination: str | None = Field(default=None, max_length=2_000)

    @field_validator("message", "source", "destination")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class ErrorResponse(BaseModel):
    """Stable API error envelope."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None

    @classmethod
    def from_error(cls, error: EtlError) -> ErrorResponse:
        return cls(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=redact_mapping(error.context) or None,
        )


class PlanOperationResponse(BaseModel):
    operation: str
    params: dict[str, Any]


class PlanTransformationResponse(PlanOperationResponse):
    step_id: str


class PlanChunkingResponse(BaseModel):
    enabled: bool
    size: int


class PlanResponse(BaseModel):
    plan_version: str
    mode: str
    run_id: str
    name: str
    description: str
    source: PlanOperationResponse | None
    transformations: list[PlanTransformationResponse]
    destination: PlanOperationResponse | None
    chunking: PlanChunkingResponse
    on_error: str
    approval_required: bool

    @classmethod
    def from_domain(cls, plan: ExecutionPlan) -> PlanResponse:
        return cls(
            plan_version=plan.plan_version,
            mode=plan.mode,
            run_id=plan.run_id,
            name=plan.name,
            description=plan.description,
            source=(
                PlanOperationResponse(
                    operation=plan.source.operation,
                    params=dict(plan.source.params),
                )
                if plan.source is not None
                else None
            ),
            transformations=[
                PlanTransformationResponse(
                    step_id=step.step_id,
                    operation=step.operation,
                    params=dict(step.params),
                )
                for step in plan.transformations
            ],
            destination=(
                PlanOperationResponse(
                    operation=plan.destination.operation,
                    params=dict(plan.destination.params),
                )
                if plan.destination is not None
                else None
            ),
            chunking=PlanChunkingResponse(
                enabled=plan.chunking.enabled,
                size=plan.chunking.size,
            ),
            on_error=plan.on_error,
            approval_required=plan.approval_required,
        )


class AssessmentIssueResponse(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    column: str | None
    details: dict[str, Any]


class AssessmentMetricResponse(BaseModel):
    metric: str
    subject: str
    value: float | None
    status: str
    approximate: bool


class DraftPlanResponse(BaseModel):
    name: str
    description: str
    source_operation: str
    source_params: dict[str, Any]
    transformations: list[PlanTransformationResponse]
    chunking: PlanChunkingResponse
    rationale: list[str]


class AssessmentResponse(BaseModel):
    assessment_id: str
    run_id: str
    source_id: str
    source_type: str
    row_count: int
    column_count: int
    content_hash: str
    schema_hash: str | None
    issues: list[AssessmentIssueResponse]
    assumptions: list[str]
    missing_inputs: list[str]
    quality: list[AssessmentMetricResponse]
    draft_plan: DraftPlanResponse
    quality_path: str | None
    info_path: str | None
    chunk_count: int

    @classmethod
    def from_report(cls, report: AssessmentReport) -> AssessmentResponse:
        draft = report.draft_plan
        return cls(
            assessment_id=report.assessment_id,
            run_id=report.run_id,
            source_id=report.source_id,
            source_type=report.source_type,
            row_count=report.row_count,
            column_count=report.column_count,
            content_hash=report.content_hash,
            schema_hash=report.schema_hash,
            issues=[
                AssessmentIssueResponse(
                    code=issue.code,
                    message=issue.message,
                    severity=issue.severity,
                    column=issue.column,
                    details=dict(issue.details),
                )
                for issue in report.issues
            ],
            assumptions=list(report.assumptions),
            missing_inputs=list(report.missing_inputs),
            quality=[
                AssessmentMetricResponse(
                    metric=metric.metric,
                    subject=metric.subject,
                    value=metric.value,
                    status=metric.status.value,
                    approximate=metric.approximate,
                )
                for metric in report.quality
            ],
            draft_plan=DraftPlanResponse(
                name=draft.name,
                description=draft.description,
                source_operation=draft.source_operation,
                source_params=dict(draft.source_params),
                transformations=[
                    PlanTransformationResponse(
                        step_id=step.step_id,
                        operation=step.operation,
                        params=dict(step.params),
                    )
                    for step in draft.transformations
                ],
                chunking=PlanChunkingResponse(
                    enabled=draft.chunking.enabled,
                    size=draft.chunking.size,
                ),
                rationale=list(draft.rationale),
            ),
            quality_path=report.quality_path,
            info_path=report.info_path,
            chunk_count=report.chunk_count,
        )


class ExecutionStepErrorResponse(BaseModel):
    step_id: str | None
    operation: str
    error_type: str
    message: str


class ExecutionResultResponse(BaseModel):
    status: Literal["success", "partial", "failed"]
    output_count: int
    data_available: bool
    errors: list[ExecutionStepErrorResponse]

    @classmethod
    def from_result(cls, result: PlanExecutionResult) -> ExecutionResultResponse:
        return cls(
            status=result.status,
            output_count=len(result.outputs),
            data_available=result.data is not None,
            errors=[
                ExecutionStepErrorResponse(
                    step_id=error.step_id,
                    operation=error.operation,
                    error_type=error.error_type,
                    message=error.message,
                )
                for error in result.errors
            ],
        )


class CleanupResponse(BaseModel):
    policy: str
    removed: list[str]
    retained: list[str]
    errors: list[str]


class RunResponse(BaseModel):
    run_id: str
    thread_id: str
    mode: str
    status: str
    approval_state: str
    plan: PlanResponse | None
    plan_hash: str | None
    registry_version: str
    attempt: int
    clarification_attempts: int
    questions: list[str]
    missing_inputs: list[str]
    error: ErrorResponse | None
    assessment_id: str | None = None
    assessment: AssessmentResponse | None = None
    created_at: datetime
    updated_at: datetime
    result: ExecutionResultResponse | None = None
    cleanup: CleanupResponse | None = None
    next_action: NextAction

    @classmethod
    def from_outcome(cls, outcome: RunOutcome) -> RunResponse:
        run = outcome.run
        return cls(
            run_id=run.run_id,
            thread_id=run.thread_id,
            mode=run.mode,
            status=run.status.value,
            approval_state=run.approval_state.value,
            plan=PlanResponse.from_domain(run.plan) if run.plan is not None else None,
            plan_hash=run.plan_hash,
            registry_version=run.registry_version,
            attempt=run.attempt,
            clarification_attempts=run.clarification_attempts,
            questions=list(run.questions),
            missing_inputs=list(run.missing_inputs),
            error=ErrorResponse.from_error(run.error) if run.error is not None else None,
            assessment_id=run.assessment_id,
            assessment=(
                AssessmentResponse.from_report(run.assessment)
                if run.assessment is not None
                else None
            ),
            created_at=run.created_at,
            updated_at=run.updated_at,
            result=(
                ExecutionResultResponse.from_result(outcome.result)
                if outcome.result is not None
                else None
            ),
            cleanup=(
                CleanupResponse(
                    policy=outcome.cleanup.policy.value,
                    removed=list(outcome.cleanup.removed),
                    retained=list(outcome.cleanup.retained),
                    errors=list(outcome.cleanup.errors),
                )
                if outcome.cleanup is not None
                else None
            ),
            next_action=_next_action(run),
        )


class RunLogEntryResponse(BaseModel):
    timestamp: datetime
    level: str
    run_id: str
    event: str
    status: str | None
    message: str | None
    step_id: str | None
    module: str
    duration_ms: float | None
    error: dict[str, Any] | None
    context: dict[str, Any]
    trace_id: str | None
    schema_version: str

    @classmethod
    def from_entry(cls, entry: RunLogEntry) -> RunLogEntryResponse:
        return cls(
            timestamp=entry.timestamp,
            level=entry.level,
            run_id=entry.run_id,
            event=entry.event,
            status=entry.status,
            message=entry.message,
            step_id=entry.step_id,
            module=entry.module,
            duration_ms=entry.duration_ms,
            error=dict(entry.error) if entry.error is not None else None,
            context=dict(entry.context),
            trace_id=entry.trace_id,
            schema_version=entry.schema_version,
        )


class RunLogsResponse(BaseModel):
    run_id: str
    logs: list[RunLogEntryResponse]


def _next_action(run: Run) -> NextAction:
    if run.status in {RunStatus.CREATED, RunStatus.AWAITING_CLARIFICATION}:
        if run.assessment is not None and run.mode == "pipeline":
            return "confirm"
        if run.mode == "assessment":
            return "provide_plan"
        if run.questions:
            return "clarify"
        return "provide_plan"
    if run.status is RunStatus.AWAITING_APPROVAL:
        return "approve"
    if run.status in {RunStatus.READY, RunStatus.RUNNING, RunStatus.RETRYING}:
        return "wait"
    return "none"


__all__ = [
    "AssessmentIssueResponse",
    "AssessmentMetricResponse",
    "AssessmentResponse",
    "CleanupResponse",
    "DraftPlanResponse",
    "ErrorResponse",
    "ExecutionResultResponse",
    "ExecutionStepErrorResponse",
    "PlanChunkingResponse",
    "PlanOperationResponse",
    "PlanResponse",
    "PlanTransformationResponse",
    "RunApprovalRequest",
    "RunConfirmRequest",
    "RunCreateRequest",
    "RunLogEntryResponse",
    "RunLogsResponse",
    "RunMessageRequest",
    "RunResponse",
]
