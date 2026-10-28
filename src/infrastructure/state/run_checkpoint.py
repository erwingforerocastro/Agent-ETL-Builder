"""Process-local checkpoint adapter for workflow runs."""

import threading

from domain.entities.run import Run


class InMemoryRunCheckpoint:
    """Stores immutable run snapshots for the lifetime of the process."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = threading.RLock()

    def save(self, run: Run) -> None:
        with self._lock:
            self._runs[run.run_id] = run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()


__all__ = ["InMemoryRunCheckpoint"]
