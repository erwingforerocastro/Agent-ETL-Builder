"""JSON-based plan size measurement."""

from __future__ import annotations

from application.validation.errors import PlanValidationErrorFactory
from domain.entities.plan import ExecutionPlan
from infrastructure.validation.plan_serialization import serialize_plan


class JsonPlanSizer:
    """Measures a plan using its canonical JSON representation."""

    def __init__(self, error_factory: PlanValidationErrorFactory | None = None) -> None:
        self._error_factory = error_factory or PlanValidationErrorFactory(module=__name__)

    def size_bytes(self, plan: ExecutionPlan) -> int:
        return len(serialize_plan(plan, error_factory=self._error_factory))


__all__ = ["JsonPlanSizer"]
