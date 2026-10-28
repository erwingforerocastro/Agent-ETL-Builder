"""Plan intake and clarification contract."""

from typing import Protocol

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
