"""Run API request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from application.ports.run_log import RunLogEntry
from application.use_cases.execution_result import PlanExecutionResult
from application.use_cases.run_outcome import RunOutcome
from domain.entities.plan import ExecutionPlan
from domain.entities.run import RunStatus
from domain.errors import EtlError

NextAction = Literal["provide_plan", "approve", "wait", "none"]


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

    @model_validator(mode="after")
    def _require_message_or_plan(self) -> RunCreateRequest:
        if self.message is None and self.plan is None:
            raise ValueError("message or plan is required")
        return self


class RunApprovalRequest(BaseModel):
    """Approval or rejection decision for a pending run."""

    model_config = ConfigDict(extra="forbid")

    approved: bool


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
            details=dict(error.context) or None,
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
            next_action=_next_action(run.status),
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
            context=dict(entry.context),
            trace_id=entry.trace_id,
            schema_version=entry.schema_version,
        )


class RunLogsResponse(BaseModel):
    run_id: str
    logs: list[RunLogEntryResponse]


def _next_action(status: RunStatus) -> NextAction:
    if status in {RunStatus.CREATED, RunStatus.AWAITING_CLARIFICATION}:
        return "provide_plan"
    if status is RunStatus.AWAITING_APPROVAL:
        return "approve"
    if status in {RunStatus.READY, RunStatus.RUNNING, RunStatus.RETRYING}:
        return "wait"
    return "none"


__all__ = [
    "CleanupResponse",
    "ErrorResponse",
    "ExecutionResultResponse",
    "ExecutionStepErrorResponse",
    "PlanChunkingResponse",
    "PlanOperationResponse",
    "PlanResponse",
    "PlanTransformationResponse",
    "RunApprovalRequest",
    "RunCreateRequest",
    "RunLogEntryResponse",
    "RunLogsResponse",
    "RunResponse",
]
