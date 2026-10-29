"""Bounded run workflow facade."""

from __future__ import annotations

from application.assessment.confirmation import build_pipeline_plan
from application.ports.approval import ApprovalPort
from application.ports.cancellation import CancellationTokenPort
from application.ports.cleanup import CleanupPort
from application.ports.clock import ClockPort
from application.ports.execution import ExecutionPort
from application.ports.module_registry import ModuleRegistryReadPort
from application.ports.plan_hasher import PlanHasherPort
from application.ports.plan_intake import PlanIntakePort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.run_checkpoint import RunCheckpointPort
from application.use_cases.run_approval import RunApprovalCoordinator
from application.use_cases.run_execution import RunExecutionCoordinator
from application.use_cases.run_intake import RunIntakeCoordinator
from application.use_cases.run_outcome import RunOutcome
from application.use_cases.run_state import RunStore, RunTerminator
from application.validation.operations import OperationCatalog, OperationSafetyPolicy
from domain.entities.run import ApprovalState, PlanRequest, Run, RunStatus, WorkflowLimits
from domain.errors import (
    PlanValidationError,
    RunAlreadyExistsError,
    RunCancelledError,
    RunExecutionError,
    RunInvalidStateError,
    RunPlanStaleError,
)


class RunWorkflow:
    """Routes one run through intake, approval, execution, and termination.

    The workflow is a plain state machine; persistence and all external effects
    are injected ports. Callers should create one instance per run.
    """

    def __init__(
        self,
        *,
        intake: PlanIntakePort,
        validator: PlanValidatorPort,
        executor: ExecutionPort,
        registry: ModuleRegistryReadPort,
        checkpoints: RunCheckpointPort,
        clock: ClockPort,
        approvals: ApprovalPort,
        cleanup: CleanupPort,
        hasher: PlanHasherPort,
        cancellation: CancellationTokenPort,
        limits: WorkflowLimits | None = None,
    ) -> None:
        self._registry = registry
        self._clock = clock
        self._validator = validator
        self._hasher = hasher
        self._cancellation = cancellation
        self._limits = limits or WorkflowLimits()
        self._store = RunStore(checkpoints)
        self._terminator = RunTerminator(self._store, clock, cleanup, self._limits)
        terminator = self._terminator
        catalog = OperationCatalog(registry)
        safety = OperationSafetyPolicy()

        self._intake = RunIntakeCoordinator(
            intake=intake,
            validator=validator,
            hasher=hasher,
            catalog=catalog,
            safety=safety,
            store=self._store,
            terminator=terminator,
            clock=clock,
            limits=self._limits,
        )
        self._approval = RunApprovalCoordinator(
            approvals=approvals,
            cancellation=cancellation,
            store=self._store,
            terminator=terminator,
            clock=clock,
            limits=self._limits,
        )
        self._execution = RunExecutionCoordinator(
            executor=executor,
            validator=validator,
            hasher=hasher,
            registry=registry,
            cancellation=cancellation,
            store=self._store,
            terminator=terminator,
            clock=clock,
            limits=self._limits,
        )
        self._run_id: str | None = None

    def start(self, request: PlanRequest) -> RunOutcome:
        """Create the run, intake a plan, validate it, and prepare approval."""
        if self._run_id is not None:
            raise RunInvalidStateError(status="initialized", operation="start")
        if self._store.get(request.run_id) is not None:
            raise RunAlreadyExistsError(run_id=request.run_id)

        self._run_id = request.run_id
        run = Run.create(
            run_id=request.run_id,
            thread_id=request.thread_id,
            mode=request.mode,
            registry_version=self._registry.snapshot().version,
            now=self._clock.now(),
        )
        self._store.save(run)
        return self._intake.prepare(request, run)

    def resume(self, request: PlanRequest) -> RunOutcome:
        """Continue a run that is waiting for clarification or repair input."""
        run = self._load()
        if run.status is not RunStatus.AWAITING_CLARIFICATION:
            raise RunInvalidStateError(status=run.status.value, operation="resume")
        if request.run_id != run.run_id or request.mode != run.mode:
            raise RunInvalidStateError(status=run.status.value, operation="resume")
        return self._intake.prepare(request, run)

    def run(self) -> RunOutcome:
        """Wait for approval if needed, then execute with bounded retries."""
        run = self._load()
        if run.status is RunStatus.AWAITING_APPROVAL:
            outcome = self._approval.wait(run)
            if outcome.run.status is not RunStatus.READY:
                return outcome
            run = outcome.run
        if run.status is RunStatus.READY:
            return self._execution.execute(run)
        return RunOutcome(run)

    def confirm(self, destination: str) -> RunOutcome:
        """Build and validate a pipeline plan from an assessed source."""
        run = self._load()
        if (
            run.status is not RunStatus.AWAITING_CLARIFICATION
            or run.assessment is None
            or run.mode != "pipeline"
        ):
            raise RunInvalidStateError(status=run.status.value, operation="confirm")
        if self._registry.snapshot().version != run.registry_version:
            return self._terminator.terminate(
                run,
                RunStatus.FAILED,
                RunPlanStaleError(reason="registry version changed"),
                cleanup=True,
            )
        try:
            plan = build_pipeline_plan(run.assessment, destination=destination)
        except ValueError as exc:
            raise PlanValidationError(
                code="PLAN_INVALID_DESTINATION",
                message=str(exc),
                module=__name__,
            ) from exc
        self._validator.validate(plan)
        try:
            plan_hash = self._hasher.hash(plan)
        except Exception as exc:
            return self._terminator.terminate(
                run,
                RunStatus.FAILED,
                RunExecutionError(error_type=type(exc).__name__),
                cleanup=True,
            )
        run = run.transition(
            RunStatus.AWAITING_APPROVAL,
            now=self._clock.now(),
            approval_state=ApprovalState.PENDING,
            plan=plan,
            plan_hash=plan_hash,
            questions=(),
            missing_inputs=(),
            error=None,
        )
        self._store.save(run)
        return RunOutcome(run)

    def approve(self, approved: bool) -> RunOutcome:
        """Record an approval decision and advance the run if approved."""
        run = self._load()
        if run.status is not RunStatus.AWAITING_APPROVAL:
            raise RunInvalidStateError(status=run.status.value, operation="approve")
        return self._approval.decide(run, approved)

    def cancel(self) -> RunOutcome:
        """Cancel the run at the next safe boundary and clean up partial output."""
        self._cancellation.cancel()
        run = self._load()
        if run.status.terminal:
            return RunOutcome(run)
        return self._terminator.terminate(
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

    def _load(self) -> Run:
        return self._store.load(self._require_run_id())

    def _require_run_id(self) -> str:
        if self._run_id is None:
            raise RunInvalidStateError(status="uninitialized", operation="load")
        return self._run_id


__all__ = ["RunOutcome", "RunWorkflow"]
