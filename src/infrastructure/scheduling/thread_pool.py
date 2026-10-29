"""Thread-pool background scheduler."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from application.ports.background_scheduler import BackgroundSchedulerPort


class ThreadPoolRunScheduler(BackgroundSchedulerPort):
    """Runs workflow tasks in a bounded process-local thread pool."""

    def __init__(self, max_workers: int = 4) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="agent-etl-run",
        )

    def submit(self, run_id: str, task: Callable[[], None]) -> None:
        del run_id
        self._executor.submit(task)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["ThreadPoolRunScheduler"]
