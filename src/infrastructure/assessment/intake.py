"""Plan intake adapter that runs a source-only assessment."""

from __future__ import annotations

from application.assessment.assess_source import AssessSourceUseCase
from application.ports.plan_intake import PlanIntakeFactoryPort, PlanIntakePort
from domain.entities.plan import ExecutionPlan
from domain.entities.run import PlanIntakeResult, PlanRequest
from domain.errors import IngestionError, PlanValidationError


class AssessmentPlanIntake:
    """Assesses a source-only request and returns a draft-plan report."""

    def __init__(self, assessor: AssessSourceUseCase) -> None:
        self._assessor = assessor

    def request(
        self,
        request: PlanRequest,
        *,
        attempt: int,
        previous_error: PlanValidationError | None = None,
    ) -> PlanIntakeResult:
        del attempt, previous_error
        if request.source is None:
            return PlanIntakeResult(
                questions=("Which workspace source should be assessed?",),
                missing_inputs=("source",),
            )
        try:
            report = self._assessor.execute(
                run_id=request.run_id,
                reference=request.source,
            )
        except IngestionError as exc:
            return PlanIntakeResult(
                questions=(f"The source could not be assessed ({exc.code}).",),
                missing_inputs=("source",),
            )
        if request.mode == "assessment":
            questions = [
                "Assessment complete. Submit a structured pipeline plan to write output.",
            ]
            if request.destination is not None:
                questions.append(
                    "Assessment mode is read-only; the destination was ignored. "
                    "Use mode 'pipeline' to write output."
                )
            return PlanIntakeResult(
                assessment=report,
                questions=tuple(questions),
            )
        return PlanIntakeResult(
            assessment=report,
            questions=("Review the assessment and confirm a destination for the draft plan.",),
            missing_inputs=("destination",),
        )


class AssessmentPlanIntakeFactory(PlanIntakeFactoryPort):
    """Creates one assessment intake adapter per run."""

    def __init__(self, assessor: AssessSourceUseCase) -> None:
        self._assessor = assessor

    def create(self, plan: ExecutionPlan | None) -> PlanIntakePort:
        del plan
        return AssessmentPlanIntake(self._assessor)


__all__ = ["AssessmentPlanIntake", "AssessmentPlanIntakeFactory"]
