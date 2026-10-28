"""Plan size measurement contract used by validation."""

from typing import Protocol

from domain.entities.plan import ExecutionPlan


class PlanSizerPort(Protocol):
    """Measures the serialized size of a plan without exposing its format."""

    def size_bytes(self, plan: ExecutionPlan) -> int: ...


__all__ = ["PlanSizerPort"]
