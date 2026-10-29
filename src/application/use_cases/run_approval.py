"""Approval stage of a run."""

from __future__ import annotations

from application.ports.approval import ApprovalPort
from application.ports.cancellation import CancellationTokenPort
from application.ports.clock import ClockPort
from application.use_cases.run_outcome import RunOutcome
from application.use_cases.run_state import RunStore, RunTerminator
from domain.entities.run import ApprovalState, Run, RunStatus, WorkflowLimits
from domain.errors import (
    RunApprovalError,
    RunApprovalRejectedError,
    RunApprovalTimeoutError,
    RunCancelledError,
)


class RunApprovalCoordinator:
    """Waits for or records human approval decisions."""

    def __init__(
        self,
        *,
        approvals: ApprovalPort,
        cancellation: CancellationTokenPort,
        store: RunStore,
        terminator: RunTerminator,
        clock: ClockPort,
        limits: WorkflowLimits,
    ) -> None:
        self._approvals = approvals
        self._cancellation = cancellation
        self._store = store
        self._terminator = terminator
        self._clock = clock
        self._limits = limits

    def wait(self, run: Run) -> RunOutcome:
        """Wait for a decision and return a ready or terminal run."""
        try:
            decision = self._approvals.request(
                run.run_id,
                timeout_seconds=self._limits.approval_timeout_seconds,
                cancellation=self._cancellation,
            )
        except Exception as exc:
            return self._terminator.terminate(
                run,
                RunStatus.FAILED,
                RunApprovalError(error_type=type(exc).__name__),
                cleanup=True,
            )

        run = self._store.load(run.run_id)
        if run.status is RunStatus.READY or run.status.terminal:
            return RunOutcome(run)
        if decision is ApprovalState.APPROVED:
            return self._approve(run)
        if decision is ApprovalState.REJECTED:
            return self._reject(run)
        if decision is ApprovalState.CANCELLED:
            return self._cancel(run)
        return self._timeout(run)

    def decide(self, run: Run, approved: bool) -> RunOutcome:
        """Record a decision and advance the run when approved."""
        try:
            if not approved:
                self._approvals.decide(run.run_id, ApprovalState.REJECTED)
                return self._reject(run)
            self._approvals.decide(run.run_id, ApprovalState.APPROVED)
        except Exception as exc:
            return self._terminator.terminate(
                run,
                RunStatus.FAILED,
                RunApprovalError(error_type=type(exc).__name__),
                cleanup=True,
            )

        latest = self._store.load(run.run_id)
        if latest.status is RunStatus.READY or latest.status.terminal:
            return RunOutcome(latest)
        return self._approve(latest)

    def _approve(self, run: Run) -> RunOutcome:
        run = run.transition(
            RunStatus.READY,
            now=self._clock.now(),
            approval_state=ApprovalState.APPROVED,
            error=None,
        )
        self._store.save(run)
        return RunOutcome(run)

    def _reject(self, run: Run) -> RunOutcome:
        return self._terminator.terminate(
            run,
            RunStatus.REJECTED,
            RunApprovalRejectedError(),
            approval_state=ApprovalState.REJECTED,
            cleanup=True,
        )

    def _cancel(self, run: Run) -> RunOutcome:
        return self._terminator.terminate(
            run,
            RunStatus.CANCELLED,
            RunCancelledError(),
            approval_state=ApprovalState.CANCELLED,
            cleanup=True,
        )

    def _timeout(self, run: Run) -> RunOutcome:
        return self._terminator.terminate(
            run,
            RunStatus.TIMED_OUT,
            RunApprovalTimeoutError(
                timeout_seconds=self._limits.approval_timeout_seconds,
            ),
            approval_state=ApprovalState.TIMED_OUT,
            cleanup=True,
        )


__all__ = ["RunApprovalCoordinator"]
