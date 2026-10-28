"""Unit tests for workflow infrastructure adapters."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.entities.plan import ExecutionPlan, PlanChunking, PlanSource
from domain.entities.run import (
    ApprovalState,
    CleanupPolicy,
    PlanIntakeResult,
    PlanRequest,
    Run,
)
from infrastructure.approval.in_memory import InMemoryApprovalGateway
from infrastructure.cancellation import EventCancellationToken
from infrastructure.cleanup.filesystem import FilesystemCleanup
from infrastructure.clock import SystemClock
from infrastructure.planning.deterministic import DeterministicPlanIntake
from infrastructure.state.run_checkpoint import InMemoryRunCheckpoint
from infrastructure.validation.plan_hasher import JsonPlanHasher


def _plan(*, description: str = "plan") -> ExecutionPlan:
    return ExecutionPlan(
        plan_version="1.0",
        mode="assessment",
        run_id="run-1",
        name="test",
        description=description,
        source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
        transformations=(),
        destination=None,
        chunking=PlanChunking(enabled=True, size=100),
        on_error="fail_fast",
        approval_required=False,
    )


def _request() -> PlanRequest:
    return PlanRequest(run_id="run-1", thread_id="thread-1", message="hello")


def test_in_memory_checkpoint_round_trips() -> None:
    checkpoint = InMemoryRunCheckpoint()
    run = Run.create(
        run_id="run-1",
        thread_id="thread-1",
        mode="assessment",
        registry_version="1.0.0",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    checkpoint.save(run)

    assert checkpoint.get("run-1") is run
    checkpoint.clear()
    assert checkpoint.get("run-1") is None


def test_event_cancellation_token() -> None:
    token = EventCancellationToken()

    assert not token.is_cancelled()
    token.cancel()
    assert token.is_cancelled()


def test_system_clock_provides_aware_time() -> None:
    clock = SystemClock()

    assert clock.now().tzinfo is not None
    assert clock.monotonic() > 0
    clock.sleep(0)


def test_approval_gateway_returns_predecided_value() -> None:
    gateway = InMemoryApprovalGateway()
    token = EventCancellationToken()
    gateway.decide("run-1", ApprovalState.APPROVED)

    assert gateway.request("run-1", timeout_seconds=1, cancellation=token) is ApprovalState.APPROVED


def test_approval_gateway_times_out() -> None:
    gateway = InMemoryApprovalGateway()
    token = EventCancellationToken()

    decision = gateway.request("run-1", timeout_seconds=0.01, cancellation=token)

    assert decision is ApprovalState.TIMED_OUT


def test_approval_gateway_honors_cancellation() -> None:
    gateway = InMemoryApprovalGateway()
    token = EventCancellationToken()
    token.cancel()

    decision = gateway.request("run-1", timeout_seconds=10, cancellation=token)

    assert decision is ApprovalState.CANCELLED


def test_approval_gateway_rejects_invalid_decision() -> None:
    gateway = InMemoryApprovalGateway()

    with pytest.raises(ValueError, match="approved or rejected"):
        gateway.decide("run-1", ApprovalState.PENDING)


def test_filesystem_cleanup_removes_partial_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "partial.csv").write_text("partial", encoding="utf-8")
    cleanup = FilesystemCleanup(tmp_path)

    result = cleanup.apply("run-1", CleanupPolicy.CLEANUP)

    assert result.removed == (str(run_dir),)
    assert not run_dir.exists()


def test_filesystem_cleanup_removes_a_file_target(tmp_path: Path) -> None:
    target = tmp_path / "run-1"
    target.write_text("partial", encoding="utf-8")
    cleanup = FilesystemCleanup(tmp_path)

    result = cleanup.apply("run-1", CleanupPolicy.CLEANUP)

    assert result.removed == (str(target),)
    assert not target.exists()


def test_filesystem_cleanup_retains_when_configured(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    cleanup = FilesystemCleanup(tmp_path)

    result = cleanup.apply("run-1", CleanupPolicy.RETAIN)

    assert result.retained == (str(run_dir),)
    assert run_dir.exists()


def test_filesystem_cleanup_rejects_unsafe_run_id(tmp_path: Path) -> None:
    cleanup = FilesystemCleanup(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-escape"

    result = cleanup.apply(f"../{tmp_path.name}-escape", CleanupPolicy.CLEANUP)

    assert result.errors
    assert not outside.exists()


def test_plan_hasher_is_stable_and_sensitive_to_content() -> None:
    hasher = JsonPlanHasher()

    assert hasher.hash(_plan()) == hasher.hash(_plan())
    assert hasher.hash(_plan()) != hasher.hash(_plan(description="different"))


def test_deterministic_intake_returns_configured_results() -> None:
    plan = _plan()
    intake = DeterministicPlanIntake([PlanIntakeResult(plan=plan)])

    first = intake.request(_request(), attempt=1)
    second = intake.request(_request(), attempt=2)

    assert first.plan is plan
    assert second.needs_input
    assert second.reason is not None
