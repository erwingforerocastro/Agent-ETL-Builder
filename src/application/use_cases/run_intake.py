"""Intake, clarification, and validation stage of a run."""

from __future__ import annotations

from application.ports.clock import ClockPort
from application.ports.plan_hasher import PlanHasherPort
from application.ports.plan_intake import PlanIntakePort
from application.ports.plan_validator import PlanValidatorPort
from application.use_cases.run_outcome import RunOutcome
from application.use_cases.run_state import RunStore, RunTerminator
from application.validation.operations import (
    OperationCatalog,
    OperationSafetyPolicy,
    iter_operations,
)
from domain.entities.plan import ExecutionPlan
from domain.entities.run import (
    ApprovalState,
    PlanIntakeResult,
    PlanRequest,
    Run,
    RunStatus,
    WorkflowLimits,
)
from domain.errors import (
    EtlError,
    PlanValidationError,
    RunClarificationExhaustedError,
    RunExecutionError,
    RunIntakeError,
)


class RunIntakeCoordinator:
    """Turns a plan request into a validated plan awaiting approval or execution."""

    def __init__(
        self,
        *,
        intake: PlanIntakePort,
        validator: PlanValidatorPort,
        hasher: PlanHasherPort,
        catalog: OperationCatalog,
        safety: OperationSafetyPolicy,
        store: RunStore,
        terminator: RunTerminator,
        clock: ClockPort,
        limits: WorkflowLimits,
    ) -> None:
        self._intake = intake
        self._validator = validator
        self._hasher = hasher
        self._catalog = catalog
        self._safety = safety
        self._store = store
        self._terminator = terminator
        self._clock = clock
        self._limits = limits

    def prepare(self, request: PlanRequest, run: Run) -> RunOutcome:
        """Intake and validate a plan, asking for clarification when needed."""
        previous_error = run.error if isinstance(run.error, PlanValidationError) else None

        while True:
            attempt = run.clarification_attempts + 1
            try:
                result = self._intake.request(
                    request,
                    attempt=attempt,
                    previous_error=previous_error,
                )
            except PlanValidationError as exc:
                previous_error = exc
                if attempt >= self._limits.max_clarification_attempts:
                    return self._terminator.terminate(
                        run,
                        RunStatus.FAILED,
                        exc,
                        cleanup=True,
                    )
                run = run.transition(
                    RunStatus.AWAITING_CLARIFICATION,
                    now=self._clock.now(),
                    clarification_attempts=attempt,
                    error=exc,
                )
                self._store.save(run)
                continue
            except EtlError as exc:
                return self._terminator.terminate(
                    run,
                    RunStatus.FAILED,
                    exc,
                    cleanup=True,
                )
            except Exception as exc:
                return self._terminator.terminate(
                    run,
                    RunStatus.FAILED,
                    RunIntakeError(error_type=type(exc).__name__),
                    cleanup=True,
                )

            if result.plan is None:
                return self._clarification_outcome(run, result, attempt)

            try:
                invalid = self._validate_intake_plan(request, result.plan)
            except Exception as exc:
                return self._terminator.terminate(
                    run,
                    RunStatus.FAILED,
                    RunIntakeError(error_type=type(exc).__name__),
                    cleanup=True,
                )
            if invalid is not None:
                previous_error = invalid
                if attempt >= self._limits.max_clarification_attempts:
                    return self._terminator.terminate(
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
                self._store.save(run)
                continue

            return self._prepare_for_execution(run, result.plan)

    def _clarification_outcome(
        self,
        run: Run,
        result: PlanIntakeResult,
        attempt: int,
    ) -> RunOutcome:
        if attempt >= self._limits.max_clarification_attempts:
            return self._terminator.terminate(
                run,
                RunStatus.FAILED,
                RunClarificationExhaustedError(attempts=attempt),
                cleanup=True,
            )
        questions = result.questions or ((result.reason,) if result.reason is not None else ())
        run = run.transition(
            RunStatus.AWAITING_CLARIFICATION,
            now=self._clock.now(),
            clarification_attempts=attempt,
            questions=questions,
            missing_inputs=result.missing_inputs,
            error=None,
            assessment=result.assessment,
        )
        self._store.save(run)
        return RunOutcome(run)

    def _prepare_for_execution(self, run: Run, plan: ExecutionPlan) -> RunOutcome:
        try:
            plan_hash = self._hasher.hash(plan)
            needs_approval = self._requires_approval(plan)
        except Exception as exc:
            return self._terminator.terminate(
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
            plan=plan,
            plan_hash=plan_hash,
            questions=(),
            missing_inputs=(),
            error=None,
        )
        self._store.save(run)
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
            self._safety.requires_approval(
                call,
                self._catalog.metadata(call.operation),
            )
            for call in iter_operations(plan)
        )


__all__ = ["RunIntakeCoordinator"]
