"""Plan intake adapter for an already validated or submitted plan."""

from __future__ import annotations

from application.ports.plan_intake import PlanIntakeFactoryPort, PlanIntakePort
from domain.entities.plan import ExecutionPlan
from domain.entities.run import PlanIntakeResult, PlanRequest
from domain.errors import PlanValidationError


class SubmittedPlanIntake:
    """Returns the plan supplied with the run request, if any."""

    def __init__(self, plan: ExecutionPlan | None) -> None:
        self._plan = plan

    def request(
        self,
        request: PlanRequest,
        *,
        attempt: int,
        previous_error: PlanValidationError | None = None,
    ) -> PlanIntakeResult:
        del request, attempt, previous_error
        if self._plan is not None:
            return PlanIntakeResult(plan=self._plan)
        return PlanIntakeResult(
            reason=(
                "No executable plan was provided. Plan generation is not configured "
                "in this version; submit a structured plan with the request."
            )
        )


class SubmittedPlanIntakeFactory(PlanIntakeFactoryPort):
    """Creates one submitted-plan intake adapter per run."""

    def create(self, plan: ExecutionPlan | None) -> PlanIntakePort:
        return SubmittedPlanIntake(plan)


__all__ = ["SubmittedPlanIntake", "SubmittedPlanIntakeFactory"]
