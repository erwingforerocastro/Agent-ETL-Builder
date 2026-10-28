"""Stable plan-hash contract."""

from typing import Protocol

from domain.entities.plan import ExecutionPlan


class PlanHasherPort(Protocol):
    def hash(self, plan: ExecutionPlan) -> str: ...
