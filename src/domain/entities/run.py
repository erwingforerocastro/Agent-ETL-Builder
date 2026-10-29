"""Run lifecycle entities and workflow policy."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from domain.entities._validation import (
    require_aware_datetime,
    require_non_negative_int,
    require_text,
)
from domain.entities.plan import ExecutionPlan
from domain.errors import EtlError


class RunStatus(StrEnum):
    """Lifecycle states for one run."""

    CREATED = "created"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    READY = "ready"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


class ApprovalState(StrEnum):
    """Approval state attached to a run."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class CleanupPolicy(StrEnum):
    """What to do with partial artifacts when a run terminates."""

    CLEANUP = "cleanup"
    RETAIN = "retain"


_TERMINAL_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.REJECTED,
        RunStatus.CANCELLED,
        RunStatus.TIMED_OUT,
    }
)

_ALLOWED_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset(
        {
            RunStatus.AWAITING_CLARIFICATION,
            RunStatus.READY,
            RunStatus.AWAITING_APPROVAL,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.AWAITING_CLARIFICATION: frozenset(
        {
            RunStatus.AWAITING_CLARIFICATION,
            RunStatus.READY,
            RunStatus.AWAITING_APPROVAL,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.READY: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.AWAITING_APPROVAL: frozenset(
        {
            RunStatus.READY,
            RunStatus.REJECTED,
            RunStatus.TIMED_OUT,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.RETRYING,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RETRYING: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.REJECTED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.TIMED_OUT: frozenset(),
}


@dataclass(frozen=True, slots=True)
class WorkflowLimits:
    """Bounded retry, clarification, approval, and cleanup policy."""

    max_clarification_attempts: int = 3
    max_execution_retries: int = 2
    approval_timeout_seconds: float = 300.0
    retry_backoff_seconds: float = 0.5
    max_retry_backoff_seconds: float = 5.0
    cleanup_policy: CleanupPolicy = CleanupPolicy.CLEANUP

    def __post_init__(self) -> None:
        if self.max_clarification_attempts <= 0:
            raise ValueError("max_clarification_attempts must be positive")
        if self.max_execution_retries < 0:
            raise ValueError("max_execution_retries must be non-negative")
        if not math.isfinite(self.approval_timeout_seconds) or self.approval_timeout_seconds <= 0:
            raise ValueError("approval_timeout_seconds must be a finite positive number")
        if not math.isfinite(self.retry_backoff_seconds) or self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be a finite non-negative number")
        if (
            not math.isfinite(self.max_retry_backoff_seconds)
            or self.max_retry_backoff_seconds < self.retry_backoff_seconds
        ):
            raise ValueError(
                "max_retry_backoff_seconds must be finite and at least retry_backoff_seconds"
            )
        if not isinstance(self.cleanup_policy, CleanupPolicy):
            raise ValueError("cleanup_policy must be a CleanupPolicy")

    def retry_delay(self, retry_number: int) -> float:
        """Return the bounded exponential delay before a retry."""
        if retry_number <= 0:
            return 0.0
        delay: float = self.retry_backoff_seconds * (2.0 ** (retry_number - 1))
        return min(delay, self.max_retry_backoff_seconds)


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """User-facing request accepted by the plan intake port."""

    run_id: str
    thread_id: str
    message: str
    source: str | None = None
    destination: str | None = None
    mode: str = "pipeline"

    def __post_init__(self) -> None:
        require_text(self.run_id, "run_id")
        require_text(self.thread_id, "thread_id")
        require_text(self.message, "message")
        if self.mode not in {"pipeline", "assessment"}:
            raise ValueError("mode must be 'pipeline' or 'assessment'")


@dataclass(frozen=True, slots=True)
class PlanIntakeResult:
    """Either a proposed plan or the next clarification/repair request."""

    plan: ExecutionPlan | None = None
    questions: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.plan is not None and (self.questions or self.reason):
            raise ValueError("plan and clarification data are mutually exclusive")
        if self.plan is None and not self.questions and not self.reason:
            raise ValueError("intake result must provide a plan or clarification data")
        if any(not question.strip() for question in self.questions):
            raise ValueError("clarification questions must not be blank")
        if any(not item.strip() for item in self.missing_inputs):
            raise ValueError("missing inputs must not be blank")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must not be blank")

    @property
    def needs_input(self) -> bool:
        return self.plan is None


@dataclass(frozen=True, slots=True)
class Run:
    """One bounded workflow run and its checkpointable state."""

    run_id: str
    thread_id: str
    mode: str
    status: RunStatus
    attempt: int
    approval_state: ApprovalState
    plan: ExecutionPlan | None
    plan_hash: str | None
    registry_version: str
    clarification_attempts: int
    questions: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    error: EtlError | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        require_text(self.run_id, "run_id")
        require_text(self.thread_id, "thread_id")
        require_text(self.registry_version, "registry_version")
        if self.mode not in {"pipeline", "assessment"}:
            raise ValueError("mode must be 'pipeline' or 'assessment'")
        require_non_negative_int(self.attempt, "attempt")
        require_non_negative_int(self.clarification_attempts, "clarification_attempts")
        if not isinstance(self.status, RunStatus):
            raise ValueError("status must be a RunStatus")
        if not isinstance(self.approval_state, ApprovalState):
            raise ValueError("approval_state must be an ApprovalState")
        require_aware_datetime(self.created_at, "created_at")
        require_aware_datetime(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.plan_hash is not None:
            require_text(self.plan_hash, "plan_hash")
        if self.error is not None and not isinstance(self.error, EtlError):
            raise ValueError("error must be an EtlError")
        if (self.plan is None) != (self.plan_hash is None):
            raise ValueError("plan and plan_hash must be set together")
        if any(not question.strip() for question in self.questions):
            raise ValueError("questions must not be blank")
        if any(not item.strip() for item in self.missing_inputs):
            raise ValueError("missing_inputs must not be blank")

        if (
            self.status is RunStatus.AWAITING_APPROVAL
            and self.approval_state is not ApprovalState.PENDING
        ):
            raise ValueError("awaiting approval runs must have a pending approval state")
        if self.status is RunStatus.READY and self.approval_state not in {
            ApprovalState.NOT_REQUIRED,
            ApprovalState.APPROVED,
        }:
            raise ValueError("ready runs must be approved or not require approval")
        if self.status is RunStatus.REJECTED and self.approval_state is not ApprovalState.REJECTED:
            raise ValueError("rejected runs must have a rejected approval state")
        if self.status is RunStatus.TIMED_OUT and self.approval_state not in {
            ApprovalState.TIMED_OUT,
            ApprovalState.APPROVED,
            ApprovalState.NOT_REQUIRED,
        }:
            raise ValueError("timed-out runs have an invalid approval state")
        if (
            self.status
            in {
                RunStatus.AWAITING_APPROVAL,
                RunStatus.READY,
                RunStatus.RUNNING,
                RunStatus.RETRYING,
                RunStatus.SUCCEEDED,
                RunStatus.REJECTED,
                RunStatus.TIMED_OUT,
            }
            and self.plan is None
        ):
            raise ValueError(f"{self.status} runs must have a plan")

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        thread_id: str,
        mode: str,
        registry_version: str,
        now: datetime,
    ) -> Run:
        require_aware_datetime(now, "now")
        return cls(
            run_id=run_id,
            thread_id=thread_id,
            mode=mode,
            status=RunStatus.CREATED,
            attempt=0,
            approval_state=ApprovalState.NOT_REQUIRED,
            plan=None,
            plan_hash=None,
            registry_version=registry_version,
            clarification_attempts=0,
            questions=(),
            missing_inputs=(),
            error=None,
            created_at=now,
            updated_at=now,
        )

    def transition(
        self,
        status: RunStatus,
        *,
        now: datetime,
        approval_state: ApprovalState | None = None,
        attempt: int | None = None,
        plan: ExecutionPlan | None = None,
        plan_hash: str | None = None,
        clarification_attempts: int | None = None,
        questions: tuple[str, ...] | None = None,
        missing_inputs: tuple[str, ...] | None = None,
        error: EtlError | None = None,
    ) -> Run:
        """Return the next run state, enforcing lifecycle transitions."""
        require_aware_datetime(now, "now")
        if self.status.terminal:
            raise ValueError(f"run is already terminal: {self.status}")
        allowed = _ALLOWED_TRANSITIONS[self.status]
        if status not in allowed:
            raise ValueError(f"invalid run transition: {self.status} -> {status}")
        return replace(
            self,
            status=status,
            approval_state=self.approval_state if approval_state is None else approval_state,
            attempt=self.attempt if attempt is None else attempt,
            plan=self.plan if plan is None else plan,
            plan_hash=self.plan_hash if plan_hash is None else plan_hash,
            clarification_attempts=(
                self.clarification_attempts
                if clarification_attempts is None
                else clarification_attempts
            ),
            questions=self.questions if questions is None else questions,
            missing_inputs=self.missing_inputs if missing_inputs is None else missing_inputs,
            error=error,
            updated_at=now,
        )


__all__ = [
    "ApprovalState",
    "CleanupPolicy",
    "PlanIntakeResult",
    "PlanRequest",
    "Run",
    "RunStatus",
    "WorkflowLimits",
]
