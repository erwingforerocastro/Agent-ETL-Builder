"""Plan validator port."""

from typing import Protocol

from domain.entities.plan import ExecutionPlan


class PlanValidatorPort(Protocol):
    def validate(self, plan: ExecutionPlan) -> None: ...
