"""Run persistence and terminal-state policy."""

from __future__ import annotations

from application.ports.cleanup import CleanupPort, CleanupResult
from application.ports.clock import ClockPort
from application.ports.run_checkpoint import RunCheckpointPort
from application.use_cases.run_outcome import RunOutcome
from domain.entities.run import ApprovalState, Run, RunStatus, WorkflowLimits
from domain.errors import EtlError, RunNotFoundError


class RunStore:
    """Loads and saves immutable run snapshots."""

    def __init__(self, checkpoints: RunCheckpointPort) -> None:
        self._checkpoints = checkpoints

    def load(self, run_id: str) -> Run:
        run = self._checkpoints.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id=run_id)
        return run

    def get(self, run_id: str) -> Run | None:
        return self._checkpoints.get(run_id)

    def save(self, run: Run) -> None:
        self._checkpoints.save(run)


class RunTerminator:
    """Moves runs to terminal states and applies cleanup policy."""

    def __init__(
        self,
        store: RunStore,
        clock: ClockPort,
        cleanup: CleanupPort,
        limits: WorkflowLimits,
    ) -> None:
        self._store = store
        self._clock = clock
        self._cleanup = cleanup
        self._limits = limits

    def terminate(
        self,
        run: Run,
        status: RunStatus,
        error: EtlError,
        *,
        approval_state: ApprovalState | None = None,
        cleanup: bool,
    ) -> RunOutcome:
        latest = self._store.load(run.run_id)
        if latest.status.terminal:
            return RunOutcome(latest)

        latest = latest.transition(
            status,
            now=self._clock.now(),
            approval_state=approval_state,
            error=error,
        )
        self._store.save(latest)
        cleanup_result = self.apply_cleanup(latest) if cleanup else None
        return RunOutcome(latest, cleanup=cleanup_result)

    def apply_cleanup(self, run: Run) -> CleanupResult:
        try:
            return self._cleanup.apply(run.run_id, self._limits.cleanup_policy)
        except Exception as exc:
            return CleanupResult(
                policy=self._limits.cleanup_policy,
                errors=(type(exc).__name__,),
            )


__all__ = ["RunStore", "RunTerminator"]
