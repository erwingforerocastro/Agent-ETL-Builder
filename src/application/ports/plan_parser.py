"""Plan payload parsing contract used by the run API."""

from collections.abc import Mapping
from typing import Protocol

from domain.entities.plan import ExecutionPlan


class PlanParserPort(Protocol):
    """Parses an untrusted JSON-compatible plan payload into a domain plan."""

    def parse(self, payload: Mapping[str, object]) -> ExecutionPlan: ...


__all__ = ["PlanParserPort"]
