"""Stable SHA-256 hashing for execution plans."""

from __future__ import annotations

import hashlib

from application.validation.errors import PlanValidationErrorFactory
from domain.entities.plan import ExecutionPlan
from infrastructure.validation.plan_serialization import serialize_plan


class JsonPlanHasher:
    """Hashes a plan using its canonical JSON representation."""

    def __init__(self, error_factory: PlanValidationErrorFactory | None = None) -> None:
        self._error_factory = error_factory or PlanValidationErrorFactory(module=__name__)

    def hash(self, plan: ExecutionPlan) -> str:
        return hashlib.sha256(serialize_plan(plan, error_factory=self._error_factory)).hexdigest()


__all__ = ["JsonPlanHasher"]
