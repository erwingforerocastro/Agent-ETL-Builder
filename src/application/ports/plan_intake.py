"""Plan intake and clarification contracts."""

from typing import Protocol

from domain.entities.plan import ExecutionPlan
from domain.entities.run import PlanIntakeResult, PlanRequest
from domain.errors import PlanValidationError


class PlanIntakePort(Protocol):
    def request(
        self,
        request: PlanRequest,
        *,
        attempt: int,
        previous_error: PlanValidationError | None = None,
    ) -> PlanIntakeResult: ...


class PlanIntakeFactoryPort(Protocol):
    """Creates the intake adapter for one run."""

    def create(self, plan: ExecutionPlan | None) -> PlanIntakePort: ...


__all__ = ["PlanIntakeFactoryPort", "PlanIntakePort"]
