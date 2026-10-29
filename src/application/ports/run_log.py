"""Run log contract used by the API and workflow manager."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RunLogEntry:
    """One structured run event."""

    timestamp: datetime
    level: str
    run_id: str
    event: str
    status: str | None = None
    message: str | None = None
    step_id: str | None = None
    module: str = "run_manager"
    duration_ms: float | None = None
    context: Mapping[str, object] = field(default_factory=dict)
    trace_id: str | None = None
    schema_version: str = "1.0"


class RunLogPort(Protocol):
    """Appends and reads structured run events."""

    def append(self, entry: RunLogEntry) -> None: ...

    def entries(self, run_id: str) -> tuple[RunLogEntry, ...]: ...


__all__ = ["RunLogEntry", "RunLogPort"]
