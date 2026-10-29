"""Background execution contract used by the run API."""

from collections.abc import Callable
from typing import Protocol


class BackgroundSchedulerPort(Protocol):
    """Schedules one run task outside the request thread."""

    def submit(self, run_id: str, task: Callable[[], None]) -> None: ...


__all__ = ["BackgroundSchedulerPort"]
