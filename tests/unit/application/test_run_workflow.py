"""Unit tests for the bounded run workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from application.ports.approval import ApprovalPort
from application.ports.cancellation import CancellationTokenPort
from application.ports.cleanup import CleanupResult
from application.ports.module_registry import ModuleRegistryPort
from application.ports.plan_intake import PlanIntakePort
from application.registry.specs import MODULE_SPECS
from application.use_cases.execution_result import PlanExecutionResult
from application.use_cases.run_workflow import RunWorkflow
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from domain.entities.registry import ModuleMetadata, RegistrySnapshot
from domain.entities.run import (
    ApprovalState,
    CleanupPolicy,
    PlanIntakeResult,
    PlanRequest,
    Run,
    RunStatus,
    WorkflowLimits,
)
from domain.errors import (
    PlanValidationError,
    RunAlreadyExistsError,
    RunCancelledError,
    RunInvalidStateError,
    RunNotFoundError,
    TransformationError,
)
from infrastructure.cancellation import EventCancellationToken
from infrastructure.planning.deterministic import DeterministicPlanIntake
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.sandbox import SandboxTimeoutError, SandboxViolationError
from infrastructure.state.run_checkpoint import InMemoryRunCheckpoint

REGISTRY = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)


def _request(*, mode: str = "pipeline", run_id: str = "run-1") -> PlanRequest:
    return PlanRequest(
        run_id=run_id,
        thread_id=f"thread-{run_id}",
        message="Build a pipeline",
        mode=mode,
    )


def _assessment_plan(*, run_id: str = "run-1") -> ExecutionPlan:
    return ExecutionPlan(
        plan_version="1.0",
        mode="assessment",
        run_id=run_id,
        name="assess",
        description="Assess the source",
        source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"]},
            ),
        ),
        destination=None,
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=False,
    )


def _write_plan(*, run_id: str = "run-1") -> ExecutionPlan:
    return ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id=run_id,
        name="write",
        description="Write the output",
        source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"]},
            ),
        ),
        destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=False,
    )


class _AcceptingValidator:
    def __init__(self) -> None:
        self.calls = 0

    def validate(self, plan: ExecutionPlan) -> None:
        self.calls += 1


class _SequenceValidator:
    def __init__(self, errors: list[PlanValidationError] | None = None) -> None:
        self._errors = list(errors or [])
        self.calls = 0

    def validate(self, plan: ExecutionPlan) -> None:
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)


class _Hasher:
    def __init__(self, *values: str) -> None:
        self._values = values or ("hash-1",)
        self.calls = 0

    def hash(self, plan: ExecutionPlan) -> str:
        self.calls += 1
        return self._values[min(self.calls - 1, len(self._values) - 1)]


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return 0.0

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class _Approval:
    def __init__(self, decision: ApprovalState | None = None) -> None:
        self.decision = decision
        self.decisions: list[tuple[str, ApprovalState]] = []

    def request(
        self,
        run_id: str,
        *,
        timeout_seconds: float,
        cancellation: CancellationTokenPort,
    ) -> ApprovalState:
        if cancellation.is_cancelled():
            return ApprovalState.CANCELLED
        return self.decision or ApprovalState.TIMED_OUT

    def decide(self, run_id: str, decision: ApprovalState) -> None:
        self.decisions.append((run_id, decision))
        self.decision = decision


class _Cleanup:
    def __init__(self, *, raise_error: bool = False) -> None:
        self.calls: list[tuple[str, CleanupPolicy]] = []
        self._raise_error = raise_error

    def apply(self, run_id: str, policy: CleanupPolicy) -> CleanupResult:
        self.calls.append((run_id, policy))
        if self._raise_error:
            raise RuntimeError("cleanup failed")
        return CleanupResult(
            policy=policy, removed=(run_id,) if policy is CleanupPolicy.CLEANUP else ()
        )


class _RaisingIntake:
    def request(
        self,
        request: PlanRequest,
        *,
        attempt: int,
        previous_error: PlanValidationError | None = None,
    ) -> PlanIntakeResult:
        raise RuntimeError("intake failed")


class _RaisingApproval:
    def request(
        self,
        run_id: str,
        *,
        timeout_seconds: float,
        cancellation: CancellationTokenPort,
    ) -> ApprovalState:
        raise RuntimeError("approval failed")

    def decide(self, run_id: str, decision: ApprovalState) -> None:
        raise RuntimeError("approval failed")


class _MutableRegistry:
    def __init__(self, registry: ModuleRegistryPort) -> None:
        self._registry = registry
        self.version = registry.snapshot().version

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(
            version=self.version,
            modules=self._registry.snapshot().modules,
        )

    def get(
        self,
        name: str,
        *,
        version: str | None = None,
    ) -> ModuleMetadata | None:
        return self._registry.get(name, version=version)

    def require(self, name: str, *, version: str | None = None) -> ModuleMetadata:
        return self._registry.require(name, version=version)

    def function_for(self, name: str, *, version: str | None = None) -> Callable[..., Any]:
        return self._registry.function_for(name, version=version)


class _Executor:
    def __init__(self, outcomes: list[PlanExecutionResult | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def execute(
        self,
        plan: ExecutionPlan,
        *,
        cancellation: CancellationTokenPort | None = None,
    ) -> PlanExecutionResult:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass
class _Harness:
    workflow: RunWorkflow
    executor: _Executor
    approval: ApprovalPort
    cleanup: _Cleanup
    clock: _Clock
    checkpoint: InMemoryRunCheckpoint


def _success() -> PlanExecutionResult:
    return PlanExecutionResult(status="success", outputs=())


def _build(
    results: list[PlanIntakeResult],
    *,
    executor: _Executor | None = None,
    validator: _AcceptingValidator | _SequenceValidator | None = None,
    intake: PlanIntakePort | None = None,
    approval: ApprovalPort | None = None,
    cleanup: _Cleanup | None = None,
    hasher: _Hasher | None = None,
    limits: WorkflowLimits | None = None,
    checkpoint: InMemoryRunCheckpoint | None = None,
    registry: ModuleRegistryPort | None = None,
) -> _Harness:
    run_executor = executor or _Executor([_success()])
    run_approval: ApprovalPort = approval or _Approval()
    run_cleanup = cleanup or _Cleanup()
    run_clock = _Clock()
    run_checkpoint = checkpoint or InMemoryRunCheckpoint()
    workflow = RunWorkflow(
        intake=intake or DeterministicPlanIntake(results),
        validator=validator or _AcceptingValidator(),
        executor=run_executor,
        registry=registry or REGISTRY,
        checkpoints=run_checkpoint,
        clock=run_clock,
        approvals=run_approval,
        cleanup=run_cleanup,
        hasher=hasher or _Hasher(),
        cancellation=EventCancellationToken(),
        limits=limits,
    )
    return _Harness(workflow, run_executor, run_approval, run_cleanup, run_clock, run_checkpoint)


def test_start_prepares_ready_assessment_run() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])

    outcome = harness.workflow.start(_request(mode="assessment"))

    assert outcome.run.status is RunStatus.READY
    assert outcome.run.plan_hash == "hash-1"
    assert outcome.run.clarification_attempts == 0
    assert harness.checkpoint.get("run-1") == outcome.run


def test_write_plan_requires_approval_even_when_flag_is_false() -> None:
    harness = _build([PlanIntakeResult(plan=_write_plan())])

    outcome = harness.workflow.start(_request())

    assert outcome.run.status is RunStatus.AWAITING_APPROVAL
    assert outcome.run.approval_state is ApprovalState.PENDING


def test_approved_write_plan_executes() -> None:
    harness = _build([PlanIntakeResult(plan=_write_plan())])
    harness.workflow.start(_request())

    approved = harness.workflow.approve(True)
    outcome = harness.workflow.run()

    assert approved.run.status is RunStatus.READY
    assert outcome.run.status is RunStatus.SUCCEEDED
    assert harness.executor.calls == 1


def test_run_waits_for_approval_decision() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_write_plan())],
        approval=_Approval(ApprovalState.APPROVED),
    )
    harness.workflow.start(_request())

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.SUCCEEDED
    assert harness.executor.calls == 1


def test_rejected_plan_is_terminal_and_cleans_up() -> None:
    harness = _build([PlanIntakeResult(plan=_write_plan())])
    harness.workflow.start(_request())

    outcome = harness.workflow.approve(False)

    assert outcome.run.status is RunStatus.REJECTED
    assert harness.executor.calls == 0
    assert harness.cleanup.calls == [("run-1", CleanupPolicy.CLEANUP)]


def test_approval_timeout_is_terminal() -> None:
    harness = _build([PlanIntakeResult(plan=_write_plan())])
    harness.workflow.start(_request())

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.TIMED_OUT
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_APPROVAL_TIMEOUT"
    assert harness.executor.calls == 0


def test_clarification_then_resume() -> None:
    harness = _build(
        [
            PlanIntakeResult(questions=("Which source?",), missing_inputs=("source",)),
            PlanIntakeResult(plan=_assessment_plan()),
        ]
    )
    first = harness.workflow.start(_request(mode="assessment"))

    assert first.run.status is RunStatus.AWAITING_CLARIFICATION
    assert first.run.clarification_attempts == 1
    assert first.run.questions == ("Which source?",)

    resumed = harness.workflow.resume(_request(mode="assessment"))
    assert resumed.run.status is RunStatus.READY
    assert resumed.run.clarification_attempts == 1


def test_clarification_exhaustion_is_terminal() -> None:
    harness = _build(
        [
            PlanIntakeResult(questions=("Q1",)),
            PlanIntakeResult(questions=("Q2",)),
            PlanIntakeResult(questions=("Q3",)),
        ]
    )
    harness.workflow.start(_request(mode="assessment"))
    harness.workflow.resume(_request(mode="assessment"))

    outcome = harness.workflow.resume(_request(mode="assessment"))

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_CLARIFICATION_EXHAUSTED"
    assert outcome.cleanup is not None


def test_invalid_plan_is_repaired_within_budget() -> None:
    invalid = PlanValidationError(
        code="PLAN_INVALID_SCHEMA",
        message="invalid",
        module="test",
    )
    validator = _SequenceValidator([invalid])
    harness = _build(
        [
            PlanIntakeResult(plan=_assessment_plan()),
            PlanIntakeResult(plan=_assessment_plan()),
        ],
        validator=validator,
    )

    outcome = harness.workflow.start(_request(mode="assessment"))

    assert outcome.run.status is RunStatus.READY
    assert outcome.run.clarification_attempts == 1
    assert validator.calls == 2


def test_retry_then_success() -> None:
    retryable = TransformationError(
        code="TEMPORARY",
        message="temporary",
        module="test",
        retryable=True,
    )
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([retryable, _success()]),
        limits=WorkflowLimits(retry_backoff_seconds=0.5),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.SUCCEEDED
    assert outcome.run.attempt == 2
    assert harness.clock.sleeps == [0.5]


def test_retry_exhaustion_is_terminal() -> None:
    retryable = TransformationError(
        code="TEMPORARY",
        message="temporary",
        module="test",
        retryable=True,
    )
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([retryable, retryable, retryable]),
        limits=WorkflowLimits(retry_backoff_seconds=0.5),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.attempt == 3
    assert outcome.run.error is not None
    assert outcome.run.error.code == "TEMPORARY"
    assert harness.clock.sleeps == [0.5, 1.0]
    assert outcome.cleanup is not None


def test_cancel_before_execution() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.cancel()

    assert outcome.run.status is RunStatus.CANCELLED
    assert harness.executor.calls == 0
    assert harness.cleanup.calls


def test_cancel_during_execution() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([RunCancelledError()]),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.CANCELLED
    assert harness.cleanup.calls


def test_cleanup_policy_retain_is_used() -> None:
    retryable = TransformationError(
        code="TEMPORARY",
        message="temporary",
        module="test",
        retryable=True,
    )
    cleanup = _Cleanup()
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([retryable, retryable, retryable]),
        cleanup=cleanup,
        limits=WorkflowLimits(cleanup_policy=CleanupPolicy.RETAIN),
    )
    harness.workflow.start(_request(mode="assessment"))

    harness.workflow.run()

    assert cleanup.calls == [("run-1", CleanupPolicy.RETAIN)]


def test_stale_plan_hash_fails_before_execution() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        hasher=_Hasher("hash-1", "hash-2"),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_PLAN_STALE"
    assert harness.executor.calls == 0
    assert harness.cleanup.calls


def test_duplicate_run_id_is_rejected() -> None:
    checkpoint = InMemoryRunCheckpoint()
    checkpoint.save(
        Run.create(
            run_id="run-1",
            thread_id="thread-1",
            mode="assessment",
            registry_version=REGISTRY.snapshot().version,
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        checkpoint=checkpoint,
    )

    with pytest.raises(RunAlreadyExistsError):
        harness.workflow.start(_request(mode="assessment"))


def test_start_twice_is_rejected() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])
    harness.workflow.start(_request(mode="assessment"))

    with pytest.raises(RunInvalidStateError):
        harness.workflow.start(_request(mode="assessment"))


def test_resume_requires_clarification_state() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])
    harness.workflow.start(_request(mode="assessment"))

    with pytest.raises(RunInvalidStateError):
        harness.workflow.resume(_request(mode="assessment"))


def test_result_is_exposed_on_success() -> None:
    result = PlanExecutionResult(status="success", outputs=("saved",))
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([result]),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.result is result


def test_cleanup_adapter_is_used_by_default() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.cancel()

    assert outcome.cleanup is not None
    assert outcome.cleanup.removed == ("run-1",)


def test_execution_error_is_wrapped_as_workflow_error() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([ValueError("boom")]),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_EXECUTION_FAILED"
    assert cast(str, outcome.run.error.context["error_type"]) == "ValueError"


def test_intake_exception_is_terminal() -> None:
    harness = _build([], intake=_RaisingIntake())

    outcome = harness.workflow.start(_request(mode="assessment"))

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_INTAKE_FAILED"
    assert harness.cleanup.calls


def test_approval_exception_is_terminal() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_write_plan())],
        approval=_RaisingApproval(),
    )
    harness.workflow.start(_request())

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_APPROVAL_FAILED"
    assert harness.executor.calls == 0


def test_cleanup_failure_keeps_terminal_state() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        cleanup=_Cleanup(raise_error=True),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.cancel()

    assert outcome.run.status is RunStatus.CANCELLED
    assert outcome.cleanup is not None
    assert outcome.cleanup.errors == ("RuntimeError",)


def test_cancel_after_success_is_idempotent() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])
    harness.workflow.start(_request(mode="assessment"))
    harness.workflow.run()

    outcome = harness.workflow.cancel()

    assert outcome.run.status is RunStatus.SUCCEEDED
    assert harness.cleanup.calls == []


def test_approve_requires_awaiting_state() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])
    harness.workflow.start(_request(mode="assessment"))

    with pytest.raises(RunInvalidStateError):
        harness.workflow.approve(True)


def test_mode_mismatch_fails_validation() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_write_plan())],
        limits=WorkflowLimits(max_clarification_attempts=1),
    )

    outcome = harness.workflow.start(_request(mode="assessment"))

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "PLAN_MODE_MISMATCH"


def test_run_id_mismatch_fails_validation() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan(run_id="different"))],
        limits=WorkflowLimits(max_clarification_attempts=1),
    )

    outcome = harness.workflow.start(_request(mode="assessment"))

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "PLAN_RUN_ID_MISMATCH"


def test_run_before_start_is_rejected() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])

    with pytest.raises(RunInvalidStateError):
        harness.workflow.run()


def test_resume_with_different_run_id_is_rejected() -> None:
    harness = _build(
        [
            PlanIntakeResult(questions=("Which source?",)),
            PlanIntakeResult(plan=_assessment_plan()),
        ]
    )
    harness.workflow.start(_request(mode="assessment"))

    with pytest.raises(RunInvalidStateError):
        harness.workflow.resume(_request(mode="assessment", run_id="different"))


def test_resume_with_different_mode_is_rejected() -> None:
    harness = _build(
        [
            PlanIntakeResult(questions=("Which source?",)),
            PlanIntakeResult(plan=_assessment_plan()),
        ]
    )
    harness.workflow.start(_request(mode="assessment"))

    with pytest.raises(RunInvalidStateError):
        harness.workflow.resume(_request(mode="pipeline"))


def test_registry_version_change_makes_plan_stale() -> None:
    registry = _MutableRegistry(REGISTRY)
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        registry=registry,
    )
    harness.workflow.start(_request(mode="assessment"))
    registry.version = "2.0.0"

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_PLAN_STALE"
    assert harness.executor.calls == 0


def test_approve_gateway_failure_is_terminal() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_write_plan())],
        approval=_RaisingApproval(),
    )
    harness.workflow.start(_request())

    outcome = harness.workflow.approve(True)

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_APPROVAL_FAILED"


def test_approval_decision_rejected_path() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_write_plan())],
        approval=_Approval(ApprovalState.REJECTED),
    )
    harness.workflow.start(_request())

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.REJECTED
    assert harness.executor.calls == 0


def test_approval_decision_cancelled_path() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_write_plan())],
        approval=_Approval(ApprovalState.CANCELLED),
    )
    harness.workflow.start(_request())

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.CANCELLED
    assert harness.executor.calls == 0


def test_failed_execution_result_is_terminal() -> None:
    failed = PlanExecutionResult(status="failed", outputs=())
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([failed]),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "RUN_EXECUTION_FAILED"
    assert outcome.result is failed


def test_sandbox_timeout_maps_to_timed_out() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([SandboxTimeoutError()]),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.TIMED_OUT
    assert outcome.run.error is not None
    assert outcome.run.error.code == "SANDBOX_TIMEOUT"


def test_sandbox_violation_maps_to_failed() -> None:
    harness = _build(
        [PlanIntakeResult(plan=_assessment_plan())],
        executor=_Executor([SandboxViolationError()]),
    )
    harness.workflow.start(_request(mode="assessment"))

    outcome = harness.workflow.run()

    assert outcome.run.status is RunStatus.FAILED
    assert outcome.run.error is not None
    assert outcome.run.error.code == "SANDBOX_VIOLATION"


def test_clarification_reason_becomes_a_question() -> None:
    harness = _build(
        [PlanIntakeResult(reason="A source file is required")],
    )

    outcome = harness.workflow.start(_request(mode="assessment"))

    assert outcome.run.status is RunStatus.AWAITING_CLARIFICATION
    assert outcome.run.questions == ("A source file is required",)


def test_get_after_checkpoint_removal_raises_not_found() -> None:
    harness = _build([PlanIntakeResult(plan=_assessment_plan())])
    harness.workflow.start(_request(mode="assessment"))
    harness.checkpoint.clear()

    with pytest.raises(RunNotFoundError):
        harness.workflow.get()
