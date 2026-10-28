"""Bounded run workflow as a plain application state machine."""

from __future__ import annotations

from dataclasses import dataclass

from application.ports.approval import ApprovalPort
from application.ports.cancellation import CancellationTokenPort
from application.ports.cleanup import CleanupPort, CleanupResult
from application.ports.clock import ClockPort
from application.ports.execution import ExecutionPort
from application.ports.module_registry import ModuleRegistryPort
from application.ports.plan_hasher import PlanHasherPort
from application.ports.plan_intake import PlanIntakePort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.run_checkpoint import RunCheckpointPort
from application.use_cases.execution_result import PlanExecutionResult
from application.validation.operations import OperationPolicy, iter_operations
from domain.entities.plan import ExecutionPlan
from domain.entities.run import (
    ApprovalState,
    PlanRequest,
    Run,
    RunStatus,
    WorkflowLimits,
)
from domain.errors import (
    EtlError,
    PlanValidationError,
    RunAlreadyExistsError,
    RunApprovalError,
    RunApprovalRejectedError,
    RunApprovalTimeoutError,
    RunCancelledError,
    RunClarificationExhaustedError,
    RunExecutionError,
    RunIntakeError,
    RunInvalidStateError,
    RunNotFoundError,
    RunPlanStaleError,
    SandboxError,
)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """The checkpointed run plus optional execution and cleanup results."""

    run: Run
    result: PlanExecutionResult | None = None
    cleanup: CleanupResult | None = None


class RunWorkflow:
    """Runs one bounded workflow from intake to a terminal state.

    The workflow is a plain state machine; persistence and all external effects
    are injected ports. Callers should create one instance per run.
    """

    def __init__(
        self,
        *,
        intake: PlanIntakePort,
        validator: PlanValidatorPort,
        executor: ExecutionPort,
        registry: ModuleRegistryPort,
        checkpoints: RunCheckpointPort,
        clock: ClockPort,
        approvals: ApprovalPort,
        cleanup: CleanupPort,
        hasher: PlanHasherPort,
        cancellation: CancellationTokenPort,
        limits: WorkflowLimits | None = None,
    ) -> None:
        self._intake = intake
        self._validator = validator
        self._executor = executor
        self._registry = registry
        self._approval_policy = OperationPolicy(registry)
        self._checkpoints = checkpoints
        self._clock = clock
        self._approvals = approvals
        self._cleanup = cleanup
        self._hasher = hasher
        self._cancellation = cancellation
        self._limits = limits or WorkflowLimits()
        self._run_id: str | None = None

    def start(self, request: PlanRequest) -> RunOutcome:
        """Create the run, intake a plan, validate it, and prepare approval."""
        if self._run_id is not None:
            raise RunInvalidStateError(status="initialized", operation="start")
        if self._checkpoints.get(request.run_id) is not None:
            raise RunAlreadyExistsError(run_id=request.run_id)

        self._run_id = request.run_id
        run = Run.create(
            run_id=request.run_id,
            thread_id=request.thread_id,
            mode=request.mode,
            registry_version=self._registry.snapshot().version,
            now=self._clock.now(),
        )
        self._save(run)
        return self._intake_and_validate(request, run)

    def resume(self, request: PlanRequest) -> RunOutcome:
        """Continue a run that is waiting for clarification or repair input."""
        run = self._load()
        if run.status is not RunStatus.AWAITING_CLARIFICATION:
            raise RunInvalidStateError(status=run.status.value, operation="resume")
        if request.run_id != run.run_id or request.mode != run.mode:
            raise RunInvalidStateError(status=run.status.value, operation="resume")
        return self._intake_and_validate(request, run)

    def run(self) -> RunOutcome:
        """Wait for approval if needed, then execute with bounded retries."""
        run = self._load()
        if run.status is RunStatus.AWAITING_APPROVAL:
            try:
                decision = self._approvals.request(
                    run.run_id,
                    timeout_seconds=self._limits.approval_timeout_seconds,
                    cancellation=self._cancellation,
                )
            except Exception as exc:
                return self._terminal(
                    run,
                    RunStatus.FAILED,
                    RunApprovalError(error_type=type(exc).__name__),
                    cleanup=True,
                )
            run = self._load()
            if run.status is RunStatus.READY:
                return self._execute(run)
            if run.status.terminal:
                return RunOutcome(run)
            if decision is ApprovalState.APPROVED:
                run = run.transition(
                    RunStatus.READY,
                    now=self._clock.now(),
                    approval_state=ApprovalState.APPROVED,
                    error=None,
                )
                self._save(run)
                return self._execute(run)
            if decision is ApprovalState.REJECTED:
                return self._terminal(
                    run,
                    RunStatus.REJECTED,
                    RunApprovalRejectedError(),
                    approval_state=ApprovalState.REJECTED,
                    cleanup=True,
                )
            if decision is ApprovalState.CANCELLED:
                return self._terminal(
                    run,
                    RunStatus.CANCELLED,
                    RunCancelledError(),
                    approval_state=ApprovalState.CANCELLED,
                    cleanup=True,
                )
            return self._terminal(
                run,
                RunStatus.TIMED_OUT,
                RunApprovalTimeoutError(
                    timeout_seconds=self._limits.approval_timeout_seconds,
                ),
                approval_state=ApprovalState.TIMED_OUT,
                cleanup=True,
            )

        if run.status is RunStatus.READY:
            return self._execute(run)
        return RunOutcome(run)

    def approve(self, approved: bool) -> RunOutcome:
        """Record an approval decision and advance the run if approved."""
        run = self._load()
        if run.status is not RunStatus.AWAITING_APPROVAL:
            raise RunInvalidStateError(status=run.status.value, operation="approve")

        try:
            if not approved:
                self._approvals.decide(run.run_id, ApprovalState.REJECTED)
                return self._terminal(
                    run,
                    RunStatus.REJECTED,
                    RunApprovalRejectedError(),
                    approval_state=ApprovalState.REJECTED,
                    cleanup=True,
                )

            self._approvals.decide(run.run_id, ApprovalState.APPROVED)
        except Exception as exc:
            return self._terminal(
                run,
                RunStatus.FAILED,
                RunApprovalError(error_type=type(exc).__name__),
                cleanup=True,
            )

        latest = self._load()
        if latest.status.terminal:
            return RunOutcome(latest)
        run = latest.transition(
            RunStatus.READY,
            now=self._clock.now(),
            approval_state=ApprovalState.APPROVED,
            error=None,
        )
        self._save(run)
        return RunOutcome(run)

    def cancel(self) -> RunOutcome:
        """Cancel the run at the next safe boundary and clean up partial output."""
        self._cancellation.cancel()
        run = self._load()
        if run.status.terminal:
            return RunOutcome(run)
        return self._terminal(
            run,
            RunStatus.CANCELLED,
            RunCancelledError(),
            approval_state=(
                ApprovalState.CANCELLED if run.status is RunStatus.AWAITING_APPROVAL else None
            ),
            cleanup=True,
        )

    def get(self) -> Run:
        """Return the latest checkpointed run."""
        return self._load()

    def _intake_and_validate(self, request: PlanRequest, run: Run) -> RunOutcome:
        previous_error = run.error if isinstance(run.error, PlanValidationError) else None

        while True:
            attempt = run.clarification_attempts + 1
            try:
                result = self._intake.request(
                    request,
                    attempt=attempt,
                    previous_error=previous_error,
                )
            except Exception as exc:
                return self._terminal(
                    run,
                    RunStatus.FAILED,
                    RunIntakeError(error_type=type(exc).__name__),
                    cleanup=True,
                )

            if result.plan is None:
                if attempt >= self._limits.max_clarification_attempts:
                    return self._terminal(
                        run,
                        RunStatus.FAILED,
                        RunClarificationExhaustedError(attempts=attempt),
                        cleanup=True,
                    )
                questions = result.questions or (
                    (result.reason,) if result.reason is not None else ()
                )
                run = run.transition(
                    RunStatus.AWAITING_CLARIFICATION,
                    now=self._clock.now(),
                    clarification_attempts=attempt,
                    questions=questions,
                    missing_inputs=result.missing_inputs,
                    error=None,
                )
                self._save(run)
                return RunOutcome(run)

            try:
                invalid = self._validate_intake_plan(request, result.plan)
            except Exception as exc:
                return self._terminal(
                    run,
                    RunStatus.FAILED,
                    RunIntakeError(error_type=type(exc).__name__),
                    cleanup=True,
                )
            if invalid is not None:
                previous_error = invalid
                if attempt >= self._limits.max_clarification_attempts:
                    return self._terminal(
                        run,
                        RunStatus.FAILED,
                        invalid,
                        cleanup=True,
                    )
                run = run.transition(
                    RunStatus.AWAITING_CLARIFICATION,
                    now=self._clock.now(),
                    clarification_attempts=attempt,
                    error=invalid,
                )
                self._save(run)
                continue

            try:
                plan_hash = self._hasher.hash(result.plan)
                needs_approval = self._requires_approval(result.plan)
            except Exception as exc:
                return self._terminal(
                    run,
                    RunStatus.FAILED,
                    RunExecutionError(error_type=type(exc).__name__),
                    cleanup=True,
                )
            run = run.transition(
                RunStatus.AWAITING_APPROVAL if needs_approval else RunStatus.READY,
                now=self._clock.now(),
                approval_state=(
                    ApprovalState.PENDING if needs_approval else ApprovalState.NOT_REQUIRED
                ),
                plan=result.plan,
                plan_hash=plan_hash,
                questions=(),
                missing_inputs=(),
                error=None,
            )
            self._save(run)
            return RunOutcome(run)

    def _validate_intake_plan(
        self,
        request: PlanRequest,
        plan: ExecutionPlan,
    ) -> PlanValidationError | None:
        if plan.run_id != request.run_id:
            return PlanValidationError(
                code="PLAN_RUN_ID_MISMATCH",
                message="Plan run_id does not match the run",
                module=__name__,
                context={"run_id": request.run_id, "plan_run_id": plan.run_id},
            )
        if plan.mode != request.mode:
            return PlanValidationError(
                code="PLAN_MODE_MISMATCH",
                message="Plan mode does not match the request mode",
                module=__name__,
                context={"mode": request.mode, "plan_mode": plan.mode},
            )
        try:
            self._validator.validate(plan)
        except PlanValidationError as exc:
            return exc
        return None

    def _requires_approval(self, plan: ExecutionPlan) -> bool:
        if plan.mode == "assessment":
            return False
        return plan.approval_required or any(
            self._approval_policy.requires_approval(call) for call in iter_operations(plan)
        )

    def _execute(self, run: Run) -> RunOutcome:
        plan = run.plan
        if plan is None:
            return self._terminal(
                run,
                RunStatus.FAILED,
                RunExecutionError(error_type="MissingPlan"),
                cleanup=True,
            )

        try:
            stale_reason = self._stale_reason(run, plan)
        except Exception as exc:
            return self._terminal(
                run,
                RunStatus.FAILED,
                RunExecutionError(error_type=type(exc).__name__),
                cleanup=True,
            )
        if stale_reason is not None:
            return self._terminal(
                run,
                RunStatus.FAILED,
                RunPlanStaleError(reason=stale_reason),
                cleanup=True,
            )

        attempt = run.attempt
        while True:
            if self._cancellation.is_cancelled():
                return self._terminal(
                    run,
                    RunStatus.CANCELLED,
                    RunCancelledError(),
                    cleanup=True,
                )

            attempt += 1
            run = run.transition(
                RunStatus.RUNNING,
                now=self._clock.now(),
                attempt=attempt,
                error=None,
            )
            self._save(run)

            try:
                result = self._executor.execute(plan, cancellation=self._cancellation)
            except RunCancelledError:
                return self._terminal(
                    run,
                    RunStatus.CANCELLED,
                    RunCancelledError(),
                    cleanup=True,
                )
            except SandboxError as exc:
                if exc.code == "SANDBOX_TIMEOUT":
                    return self._terminal(
                        run,
                        RunStatus.TIMED_OUT,
                        exc,
                        cleanup=True,
                    )
                return self._terminal(run, RunStatus.FAILED, exc, cleanup=True)
            except EtlError as exc:
                if exc.retryable and attempt <= self._limits.max_execution_retries:
                    run = run.transition(
                        RunStatus.RETRYING,
                        now=self._clock.now(),
                        error=exc,
                    )
                    self._save(run)
                    self._clock.sleep(self._limits.retry_delay(attempt))
                    if self._cancellation.is_cancelled():
                        return self._terminal(
                            run,
                            RunStatus.CANCELLED,
                            RunCancelledError(),
                            cleanup=True,
                        )
                    continue
                return self._terminal(run, RunStatus.FAILED, exc, cleanup=True)
            except Exception as exc:
                return self._terminal(
                    run,
                    RunStatus.FAILED,
                    RunExecutionError(error_type=type(exc).__name__),
                    cleanup=True,
                )

            if result.status == "failed":
                outcome = self._terminal(
                    run,
                    RunStatus.FAILED,
                    RunExecutionError(error_type="ExecutionResultFailed"),
                    cleanup=True,
                )
                return RunOutcome(outcome.run, result=result, cleanup=outcome.cleanup)

            run = run.transition(
                RunStatus.SUCCEEDED,
                now=self._clock.now(),
                error=None,
            )
            self._save(run)
            return RunOutcome(run, result=result)

    def _stale_reason(self, run: Run, plan: ExecutionPlan) -> str | None:
        if self._registry.snapshot().version != run.registry_version:
            return "registry version changed"
        if plan.run_id != run.run_id:
            return "plan run_id changed"
        if plan.mode != run.mode:
            return "plan mode changed"
        if run.plan_hash != self._hasher.hash(plan):
            return "plan hash changed"
        try:
            self._validator.validate(plan)
        except PlanValidationError:
            return "plan no longer validates"
        return None

    def _terminal(
        self,
        run: Run,
        status: RunStatus,
        error: EtlError,
        *,
        approval_state: ApprovalState | None = None,
        cleanup: bool,
    ) -> RunOutcome:
        latest = self._load()
        if latest.status.terminal:
            return RunOutcome(latest)

        latest = latest.transition(
            status,
            now=self._clock.now(),
            approval_state=approval_state,
            error=error,
        )
        self._save(latest)
        cleanup_result = self._apply_cleanup(latest) if cleanup else None
        return RunOutcome(latest, cleanup=cleanup_result)

    def _apply_cleanup(self, run: Run) -> CleanupResult:
        try:
            return self._cleanup.apply(run.run_id, self._limits.cleanup_policy)
        except Exception as exc:
            return CleanupResult(
                policy=self._limits.cleanup_policy,
                errors=(type(exc).__name__,),
            )

    def _load(self) -> Run:
        run_id = self._require_run_id()
        run = self._checkpoints.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id=run_id)
        return run

    def _require_run_id(self) -> str:
        if self._run_id is None:
            raise RunInvalidStateError(status="uninitialized", operation="load")
        return self._run_id

    def _save(self, run: Run) -> None:
        self._checkpoints.save(run)


__all__ = ["RunOutcome", "RunWorkflow"]
