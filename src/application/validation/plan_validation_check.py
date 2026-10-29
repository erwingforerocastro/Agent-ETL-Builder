"""Protocol for a single plan validation pass."""

from typing import Protocol

from domain.entities.plan import ExecutionPlan


class PlanValidationCheck(Protocol):
    """A focused validation pass over an execution plan."""

    def validate(self, plan: ExecutionPlan) -> None: ...
