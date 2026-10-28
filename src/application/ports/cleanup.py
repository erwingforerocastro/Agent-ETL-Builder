"""Cleanup contract for partial run artifacts."""

from dataclasses import dataclass
from typing import Protocol

from domain.entities.run import CleanupPolicy


@dataclass(frozen=True, slots=True)
class CleanupResult:
    policy: CleanupPolicy
    removed: tuple[str, ...] = ()
    retained: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class CleanupPort(Protocol):
    def apply(self, run_id: str, policy: CleanupPolicy) -> CleanupResult: ...
