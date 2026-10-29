"""Process-local run log adapter."""

from __future__ import annotations

import threading
from collections import defaultdict

from application.ports.run_log import RunLogEntry


class InMemoryRunLog:
    """Stores structured run events for the process lifetime."""

    def __init__(self) -> None:
        self._entries: dict[str, list[RunLogEntry]] = defaultdict(list)
        self._lock = threading.RLock()

    def append(self, entry: RunLogEntry) -> None:
        with self._lock:
            self._entries[entry.run_id].append(entry)

    def entries(self, run_id: str) -> tuple[RunLogEntry, ...]:
        with self._lock:
            return tuple(self._entries.get(run_id, ()))


__all__ = ["InMemoryRunLog"]
