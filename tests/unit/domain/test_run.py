"""Unit tests for run lifecycle entities."""

from datetime import UTC, datetime, timedelta

import pytest

from domain.entities.plan import ExecutionPlan, PlanChunking, PlanSource
from domain.entities.run import (
    ApprovalState,
    CleanupPolicy,
    PlanIntakeResult,
    PlanRequest,
    Run,
    RunStatus,
    WorkflowLimits,
)


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _run() -> Run:
    return Run.create(
        run_id="run-1",
        thread_id="thread-1",
        mode="pipeline",
        registry_version="1.0.0",
        now=_now(),
    )


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_version="1.0",
        mode="assessment",
        run_id="run-1",
        name="test",
        description="test",
        source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
        transformations=(),
        destination=None,
        chunking=PlanChunking(enabled=True, size=100),
        on_error="fail_fast",
        approval_required=False,
    )


def test_run_create_starts_created() -> None:
    run = _run()

    assert run.status is RunStatus.CREATED
    assert run.attempt == 0
    assert run.approval_state is ApprovalState.NOT_REQUIRED
    assert not run.status.terminal


def test_run_transitions_to_ready_and_preserves_plan() -> None:
    plan = _plan()

    run = _run().transition(
        RunStatus.READY,
        now=_now() + timedelta(seconds=1),
        plan=plan,
        plan_hash="hash-1",
    )

    assert run.status is RunStatus.READY
    assert run.plan is plan
    assert run.plan_hash == "hash-1"


def test_run_rejects_invalid_transition() -> None:
    with pytest.raises(ValueError, match="invalid run transition"):
        _run().transition(RunStatus.SUCCEEDED, now=_now())


def test_terminal_run_cannot_transition() -> None:
    run = _run().transition(
        RunStatus.CANCELLED,
        now=_now(),
    )

    with pytest.raises(ValueError, match="already terminal"):
        run.transition(RunStatus.READY, now=_now())


def test_ready_requires_a_plan() -> None:
    with pytest.raises(ValueError, match="must have a plan"):
        Run(
            run_id="run-1",
            thread_id="thread-1",
            mode="assessment",
            status=RunStatus.READY,
            attempt=0,
            approval_state=ApprovalState.NOT_REQUIRED,
            plan=None,
            plan_hash=None,
            registry_version="1.0.0",
            clarification_attempts=0,
            questions=(),
            missing_inputs=(),
            error=None,
            created_at=_now(),
            updated_at=_now(),
        )


def test_plan_and_plan_hash_must_be_set_together() -> None:
    with pytest.raises(ValueError, match="set together"):
        Run(
            run_id="run-1",
            thread_id="thread-1",
            mode="assessment",
            status=RunStatus.FAILED,
            attempt=0,
            approval_state=ApprovalState.NOT_REQUIRED,
            plan=_plan(),
            plan_hash=None,
            registry_version="1.0.0",
            clarification_attempts=0,
            questions=(),
            missing_inputs=(),
            error=None,
            created_at=_now(),
            updated_at=_now(),
        )


def test_awaiting_approval_requires_pending_state() -> None:
    with pytest.raises(ValueError, match="pending approval"):
        Run(
            run_id="run-1",
            thread_id="thread-1",
            mode="pipeline",
            status=RunStatus.AWAITING_APPROVAL,
            attempt=0,
            approval_state=ApprovalState.APPROVED,
            plan=None,
            plan_hash=None,
            registry_version="1.0.0",
            clarification_attempts=0,
            questions=(),
            missing_inputs=(),
            error=None,
            created_at=_now(),
            updated_at=_now(),
        )


def test_workflow_limits_validate_and_backoff() -> None:
    limits = WorkflowLimits(retry_backoff_seconds=1, max_retry_backoff_seconds=3)

    assert limits.retry_delay(1) == 1
    assert limits.retry_delay(2) == 2
    assert limits.retry_delay(3) == 3
    assert limits.retry_delay(4) == 3


def test_workflow_limits_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="max_clarification_attempts"):
        WorkflowLimits(max_clarification_attempts=0)
    with pytest.raises(ValueError, match="approval_timeout_seconds"):
        WorkflowLimits(approval_timeout_seconds=0)


def test_plan_request_requires_identity_and_message() -> None:
    with pytest.raises(ValueError, match="run_id"):
        PlanRequest(run_id=" ", thread_id="thread-1", message="hello")
    with pytest.raises(ValueError, match="message"):
        PlanRequest(run_id="run-1", thread_id="thread-1", message=" ")


def test_plan_intake_result_requires_plan_or_questions() -> None:
    with pytest.raises(ValueError, match="must provide"):
        PlanIntakeResult()

    with pytest.raises(ValueError, match="mutually exclusive"):
        PlanIntakeResult(plan=_plan(), questions=("what?",))


def test_cleanup_policy_values_are_configurable() -> None:
    assert CleanupPolicy("cleanup") is CleanupPolicy.CLEANUP
    assert CleanupPolicy("retain") is CleanupPolicy.RETAIN
