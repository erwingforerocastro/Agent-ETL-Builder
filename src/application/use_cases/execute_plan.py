"""Execute a validated plan through an injected step runner."""

from dataclasses import dataclass
from typing import Any

from application.ports.step_runner import StepRunnerPort
from domain.entities.plan import ExecutionPlan


class PlanExecutionError(Exception):
    """A validated plan could not be executed."""


@dataclass(frozen=True, slots=True)
class PlanExecutionResult:
    """Result of running a plan."""

    status: str
    outputs: tuple[object, ...]
    data: object | None = None
    include_data: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "outputs": list(self.outputs),
        }
        if self.include_data:
            result["dataframe"] = self.data
        return result


class ExecutePlanUseCase:
    """Orchestrates source, transformation, and destination steps."""

    def __init__(self, runner: StepRunnerPort) -> None:
        self._runner = runner

    def execute(self, plan: ExecutionPlan) -> PlanExecutionResult:
        data: object | None = None

        if plan.source is not None:
            data = self._runner.run_source(plan.source.operation, plan.source.params)

        for step in plan.transformations:
            if data is None:
                raise PlanExecutionError("No DataFrame available for transformation")
            try:
                data = self._runner.run_transformation(step.operation, step.params, data)
            except Exception:
                if plan.on_error == "fail_fast":
                    raise
                continue

        outputs: list[object] = []
        if plan.destination is not None:
            if data is None:
                raise PlanExecutionError("No DataFrame available for destination")
            try:
                outputs.append(
                    self._runner.run_destination(
                        plan.destination.operation,
                        plan.destination.params,
                        data,
                    )
                )
            except Exception:
                if plan.on_error == "fail_fast":
                    raise

        return PlanExecutionResult(
            status="success",
            outputs=tuple(outputs),
            data=data,
            include_data=plan.destination is None,
        )


__all__ = ["ExecutePlanUseCase", "PlanExecutionError", "PlanExecutionResult"]
