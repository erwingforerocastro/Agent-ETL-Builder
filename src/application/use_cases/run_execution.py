"""Execution and bounded-retry stage of a run."""

from __future__ import annotations

from application.ports.cancellation import CancellationTokenPort
from application.ports.clock import ClockPort
from application.ports.execution import ExecutionPort
from application.ports.module_registry import ModuleRegistryReadPort
from application.ports.plan_hasher import PlanHasherPort
from application.ports.plan_validator import PlanValidatorPort
from application.use_cases.run_outcome import RunOutcome
from application.use_cases.run_state import RunStore, RunTerminator
from domain.entities.plan import ExecutionPlan
from domain.entities.run import Run, RunStatus, WorkflowLimits
from domain.errors import (
    EtlError,
    PlanValidationError,
    RunCancelledError,
    RunExecutionError,
    RunPlanStaleError,
    SandboxError,
)


class RunExecutionCoordinator:
    """Executes a validated plan with bounded, retryable failure handling."""

    def __init__(
        self,
        *,
        executor: ExecutionPort,
        validator: PlanValidatorPort,
        hasher: PlanHasherPort,
        registry: ModuleRegistryReadPort,
        cancellation: CancellationTokenPort,
        store: RunStore,
        terminator: RunTerminator,
        clock: ClockPort,
        limits: WorkflowLimits,
    ) -> None:
        self._executor = executor
        self._validator = validator
        self._hasher = hasher
        self._registry = registry
        self._cancellation = cancellation
        self._store = store
        self._terminator = terminator
        self._clock = clock
        self._limits = limits

    def execute(self, run: Run) -> RunOutcome:
        """Execute the run's plan and return its terminal outcome."""
        plan = run.plan
        if plan is None:
            return self._failed(run, RunExecutionError(error_type="MissingPlan"))

        try:
            stale_reason = self._stale_reason(run, plan)
        except Exception as exc:
            return self._failed(run, RunExecutionError(error_type=type(exc).__name__))
        if stale_reason is not None:
            return self._failed(run, RunPlanStaleError(reason=stale_reason))

        attempt = run.attempt
        while True:
            if self._cancellation.is_cancelled():
                return self._cancelled(run)

            attempt += 1
            run = run.transition(
                RunStatus.RUNNING,
                now=self._clock.now(),
                attempt=attempt,
                error=None,
            )
            self._store.save(run)

            try:
                result = self._executor.execute(
                    plan,
                    cancellation=self._cancellation,
                    run_id=run.run_id,
                )
            except RunCancelledError:
                return self._cancelled(run)
            except SandboxError as exc:
                if exc.code == "SANDBOX_TIMEOUT":
                    return self._terminator.terminate(
                        run,
                        RunStatus.TIMED_OUT,
                        exc,
                        cleanup=True,
                    )
                return self._failed(run, exc)
            except EtlError as exc:
                if not exc.retryable or attempt > self._limits.max_execution_retries:
                    return self._failed(run, exc)
                run = run.transition(
                    RunStatus.RETRYING,
                    now=self._clock.now(),
                    error=exc,
                )
                self._store.save(run)
                self._clock.sleep(self._limits.retry_delay(attempt))
                if self._cancellation.is_cancelled():
                    return self._cancelled(run)
                continue
            except Exception as exc:
                return self._failed(run, RunExecutionError(error_type=type(exc).__name__))

            if result.status == "failed":
                outcome = self._failed(
                    run,
                    RunExecutionError(error_type="ExecutionResultFailed"),
                )
                return RunOutcome(outcome.run, result=result, cleanup=outcome.cleanup)

            run = run.transition(
                RunStatus.SUCCEEDED,
                now=self._clock.now(),
                error=None,
            )
            self._store.save(run)
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

    def _failed(self, run: Run, error: EtlError) -> RunOutcome:
        return self._terminator.terminate(
            run,
            RunStatus.FAILED,
            error,
            cleanup=True,
        )

    def _cancelled(self, run: Run) -> RunOutcome:
        return self._terminator.terminate(
            run,
            RunStatus.CANCELLED,
            RunCancelledError(),
            cleanup=True,
        )


__all__ = ["RunExecutionCoordinator"]
