"""Per-process run manager that coordinates API calls and background execution."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from application.ports.background_scheduler import BackgroundSchedulerPort
from application.ports.cancellation import CancellationTokenPort
from application.ports.clock import ClockPort
from application.ports.plan_intake import PlanIntakeFactoryPort, PlanIntakePort
from application.ports.plan_parser import PlanParserPort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.run_checkpoint import RunCheckpointPort
from application.ports.run_log import RunLogEntry, RunLogPort
from application.use_cases.run_outcome import RunOutcome
from application.use_cases.run_workflow import RunWorkflow
from domain.entities.plan import ExecutionPlan
from domain.entities.run import PlanRequest, RunStatus
from domain.errors import PlanValidationError, RunInvalidStateError, RunNotFoundError


class WorkflowFactoryPort(Protocol):
    """Creates one workflow instance for a run."""

    def create(
        self,
        *,
        intake: PlanIntakePort,
        cancellation: CancellationTokenPort,
    ) -> RunWorkflow: ...


@dataclass(frozen=True, slots=True)
class RunCreateCommand:
    """Input accepted by the run API."""

    message: str | None = None
    thread_id: str | None = None
    mode: str | None = None
    run_id: str | None = None
    source: str | None = None
    destination: str | None = None
    plan_payload: Mapping[str, object] | None = None


def _is_source_only(command: RunCreateCommand) -> bool:
    """A source without a plan or destination starts with assessment."""
    return (
        command.plan_payload is None and command.source is not None and command.destination is None
    )


class RunManager:
    """Tracks live workflows and schedules execution outside the request thread."""

    def __init__(
        self,
        *,
        workflow_factory: WorkflowFactoryPort,
        plan_parser: PlanParserPort,
        validator: PlanValidatorPort,
        intake_factory: PlanIntakeFactoryPort,
        checkpoints: RunCheckpointPort,
        run_log: RunLogPort,
        scheduler: BackgroundSchedulerPort,
        clock: ClockPort,
        cancellation_factory: Callable[[], CancellationTokenPort],
        assessment_intake_factory: PlanIntakeFactoryPort | None = None,
    ) -> None:
        self._workflow_factory = workflow_factory
        self._plan_parser = plan_parser
        self._validator = validator
        self._intake_factory = intake_factory
        self._assessment_intake_factory = assessment_intake_factory
        self._checkpoints = checkpoints
        self._run_log = run_log
        self._scheduler = scheduler
        self._clock = clock
        self._cancellation_factory = cancellation_factory
        self._lock = threading.RLock()
        self._workflows: dict[str, RunWorkflow] = {}
        self._outcomes: dict[str, RunOutcome] = {}
        self._scheduled: set[str] = set()

    def create(self, command: RunCreateCommand) -> RunOutcome:
        """Create a run, start intake, and schedule execution when ready."""
        plan = self._parse_plan(command.plan_payload)
        run_id, mode = self._resolve_identity(command, plan)
        if plan is not None:
            self._validator.validate(plan)
        request = self._request(command, run_id=run_id, mode=mode, plan=plan)
        cancellation = self._cancellation_factory()
        workflow = self._workflow_factory.create(
            intake=self._select_intake(command, plan),
            cancellation=cancellation,
        )

        outcome = workflow.start(request)
        with self._lock:
            self._workflows[run_id] = workflow
            self._outcomes[run_id] = outcome

        self._log(
            run_id,
            "run_created",
            status=outcome.run.status.value,
            context={"mode": mode, "plan_supplied": plan is not None},
        )
        if outcome.run.status is RunStatus.READY:
            self._schedule(run_id)
        return outcome

    def confirm(self, run_id: str, destination: str) -> RunOutcome:
        """Confirm an assessment and build the executable pipeline plan."""
        workflow = self._require_workflow(run_id, operation="confirm")
        outcome = workflow.confirm(destination)
        with self._lock:
            self._outcomes[run_id] = outcome
        self._log(
            run_id,
            "assessment_confirmed",
            status=outcome.run.status.value,
            context={"plan_hash": outcome.run.plan_hash},
        )
        if outcome.run.status is RunStatus.READY:
            self._schedule(run_id)
        return outcome

    def outcome(self, run_id: str) -> RunOutcome:
        """Return the latest run state plus any stored result."""
        with self._lock:
            workflow = self._workflows.get(run_id)
            stored = self._outcomes.get(run_id)
        if workflow is not None:
            run = workflow.get()
            if stored is not None and stored.run.status is run.status:
                return RunOutcome(run, result=stored.result, cleanup=stored.cleanup)
            return RunOutcome(run)

        checkpointed = self._checkpoints.get(run_id)
        if checkpointed is None:
            raise RunNotFoundError(run_id=run_id)
        if stored is not None:
            return RunOutcome(
                checkpointed,
                result=stored.result,
                cleanup=stored.cleanup,
            )
        return RunOutcome(checkpointed)

    def approve(self, run_id: str, approved: bool) -> RunOutcome:
        """Record an approval decision and schedule execution when approved."""
        workflow = self._require_workflow(run_id, operation="approve")
        outcome = workflow.approve(approved)
        with self._lock:
            self._outcomes[run_id] = outcome
        self._log(
            run_id,
            "approval_decided",
            status=outcome.run.status.value,
            context={"approved": approved},
        )
        if outcome.run.status is RunStatus.READY:
            self._schedule(run_id)
        return outcome

    def cancel(self, run_id: str) -> RunOutcome:
        """Cancel the run at the next safe boundary."""
        workflow = self._require_workflow(run_id, operation="cancel")
        outcome = workflow.cancel()
        with self._lock:
            self._outcomes[run_id] = outcome
        self._log(
            run_id,
            "cancellation_requested",
            status=outcome.run.status.value,
        )
        return outcome

    def logs(self, run_id: str) -> tuple[RunLogEntry, ...]:
        """Return structured lifecycle events for one run."""
        self._require_existing_run(run_id)
        return self._run_log.entries(run_id)

    def _run(self, run_id: str) -> None:
        with self._lock:
            workflow = self._workflows.get(run_id)
        if workflow is None:
            return
        try:
            current = workflow.get()
        except Exception:
            with self._lock:
                self._scheduled.discard(run_id)
            return
        if current.status.terminal:
            with self._lock:
                self._scheduled.discard(run_id)
            return

        self._log(run_id, "run_started", status=RunStatus.RUNNING.value)
        started = self._clock.monotonic()
        try:
            outcome = workflow.run()
        except Exception as exc:
            self._log(
                run_id,
                "run_failed",
                level="error",
                status=RunStatus.FAILED.value,
                message="Workflow raised an unexpected error",
                context={"error_type": type(exc).__name__},
            )
            with suppress(Exception):
                outcome = workflow.cancel()
                with self._lock:
                    self._outcomes[run_id] = outcome
            with self._lock:
                self._scheduled.discard(run_id)
            return

        duration_ms = (self._clock.monotonic() - started) * 1_000
        with self._lock:
            self._outcomes[run_id] = outcome
            self._scheduled.discard(run_id)
        self._log(
            run_id,
            "run_finished",
            status=outcome.run.status.value,
            duration_ms=duration_ms,
            context={
                "result_status": outcome.result.status if outcome.result is not None else None,
                "output_count": len(outcome.result.outputs) if outcome.result is not None else 0,
                "error_count": len(outcome.result.errors) if outcome.result is not None else 0,
                "error_code": outcome.run.error.code if outcome.run.error is not None else None,
            },
        )

    def _schedule(self, run_id: str) -> None:
        with self._lock:
            if run_id in self._scheduled:
                return
            self._scheduled.add(run_id)
        try:
            self._scheduler.submit(run_id, lambda: self._run(run_id))
        except Exception as exc:
            with self._lock:
                self._scheduled.discard(run_id)
            self._log(
                run_id,
                "run_schedule_failed",
                level="error",
                status=RunStatus.READY.value,
                message="Background scheduling failed",
                context={"error_type": type(exc).__name__},
            )

    def _require_workflow(self, run_id: str, *, operation: str) -> RunWorkflow:
        with self._lock:
            workflow = self._workflows.get(run_id)
        if workflow is not None:
            return workflow
        run = self._checkpoints.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id=run_id)
        raise RunInvalidStateError(status=run.status.value, operation=operation)

    def _require_existing_run(self, run_id: str) -> None:
        with self._lock:
            known = run_id in self._workflows or run_id in self._outcomes
        if known:
            return
        if self._checkpoints.get(run_id) is None:
            raise RunNotFoundError(run_id=run_id)

    def _parse_plan(self, payload: Mapping[str, object] | None) -> ExecutionPlan | None:
        return self._plan_parser.parse(payload) if payload is not None else None

    def _select_intake(
        self,
        command: RunCreateCommand,
        plan: ExecutionPlan | None,
    ) -> PlanIntakePort:
        if (
            plan is None
            and self._assessment_intake_factory is not None
            and _is_source_only(command)
        ):
            return self._assessment_intake_factory.create(None)
        return self._intake_factory.create(plan)

    def _resolve_identity(
        self,
        command: RunCreateCommand,
        plan: ExecutionPlan | None,
    ) -> tuple[str, str]:
        if plan is None:
            return command.run_id or self._generate_run_id(), command.mode or "pipeline"

        if command.run_id is not None and command.run_id != plan.run_id:
            raise PlanValidationError(
                code="PLAN_RUN_ID_MISMATCH",
                message="Plan run_id does not match the requested run_id",
                module=__name__,
                context={"run_id": command.run_id, "plan_run_id": plan.run_id},
            )
        if command.mode is not None and command.mode != plan.mode:
            raise PlanValidationError(
                code="PLAN_MODE_MISMATCH",
                message="Plan mode does not match the requested mode",
                module=__name__,
                context={"mode": command.mode, "plan_mode": plan.mode},
            )
        return plan.run_id, plan.mode

    def _request(
        self,
        command: RunCreateCommand,
        *,
        run_id: str,
        mode: str,
        plan: ExecutionPlan | None,
    ) -> PlanRequest:
        message = command.message or (plan.description if plan is not None else "Run request")
        try:
            return PlanRequest(
                run_id=run_id,
                thread_id=command.thread_id or f"thread-{run_id}",
                message=message,
                source=command.source,
                destination=command.destination,
                mode=mode,
            )
        except ValueError as exc:
            raise PlanValidationError(
                code="RUN_INVALID_REQUEST",
                message=str(exc),
                module=__name__,
            ) from exc

    def _generate_run_id(self) -> str:
        milliseconds = int(self._clock.now().timestamp() * 1_000)
        return f"{milliseconds}-{secrets.token_hex(4)}"

    def _log(
        self,
        run_id: str,
        event: str,
        *,
        level: str = "info",
        status: str | None = None,
        message: str | None = None,
        duration_ms: float | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        self._run_log.append(
            RunLogEntry(
                timestamp=self._clock.now(),
                level=level,
                run_id=run_id,
                event=event,
                status=status,
                message=message,
                duration_ms=duration_ms,
                context=context or {},
            )
        )


__all__ = ["RunCreateCommand", "RunManager", "WorkflowFactoryPort"]
