"""Transformation CSV log contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TransformLogRow:
    """One transformation step row for ``transform_log.csv``."""

    run_id: str
    filename: str
    chunk: str
    prev_step: str
    step: str
    date: datetime
    result: Mapping[str, object] = field(default_factory=dict)
    error: Mapping[str, object] | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be blank")
        if not self.step.strip():
            raise ValueError("step must not be blank")
        if self.date.tzinfo is None:
            raise ValueError("date must be timezone-aware")
        object.__setattr__(self, "result", dict(self.result))
        object.__setattr__(self, "error", dict(self.error) if self.error is not None else None)
        object.__setattr__(self, "warnings", tuple(self.warnings))


class TransformLogPort(Protocol):
    """Appends one transformation row per step."""

    def append(self, row: TransformLogRow) -> None: ...


__all__ = ["TransformLogPort", "TransformLogRow"]
