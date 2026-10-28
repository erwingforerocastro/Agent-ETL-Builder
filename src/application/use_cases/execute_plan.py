"""Execute a validated plan through an injected step runner."""

from application.ports.cancellation import CancellationTokenPort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.step_runner import StepRunnerPort
from application.use_cases.execution_result import ExecutionStepError, PlanExecutionResult
from domain.entities.plan import ExecutionPlan
from domain.errors import RunCancelledError, SandboxError


class PlanExecutionError(Exception):
    """A validated plan could not be executed."""


def _raise_if_cancelled(cancellation: CancellationTokenPort | None) -> None:
    if cancellation is not None and cancellation.is_cancelled():
        raise RunCancelledError


class ExecutePlanUseCase:
    """Orchestrates source, transformation, and destination steps."""

    def __init__(self, runner: StepRunnerPort, validator: PlanValidatorPort) -> None:
        self._runner = runner
        self._validator = validator

    def execute(
        self,
        plan: ExecutionPlan,
        *,
        cancellation: CancellationTokenPort | None = None,
    ) -> PlanExecutionResult:
        self._validator.validate(plan)
        _raise_if_cancelled(cancellation)

        errors: list[ExecutionStepError] = []
        data: object | None = None

        if plan.source is not None:
            data = self._runner.run_source(plan.source.operation, plan.source.params)
            _raise_if_cancelled(cancellation)

        for step in plan.transformations:
            if data is None:
                raise PlanExecutionError("No DataFrame available for transformation")
            _raise_if_cancelled(cancellation)
            try:
                data = self._runner.run_transformation(step.operation, step.params, data)
            except (RunCancelledError, SandboxError):
                raise
            except Exception as exc:
                if plan.on_error == "fail_fast":
                    raise
                errors.append(
                    ExecutionStepError(
                        step_id=step.step_id,
                        operation=step.operation,
                        error_type=type(exc).__name__,
                        message="Transformation failed",
                    )
                )
            _raise_if_cancelled(cancellation)

        outputs: list[object] = []
        if plan.destination is not None:
            if data is None:
                raise PlanExecutionError("No DataFrame available for destination")
            _raise_if_cancelled(cancellation)
            try:
                outputs.append(
                    self._runner.run_destination(
                        plan.destination.operation,
                        plan.destination.params,
                        data,
                    )
                )
            except (RunCancelledError, SandboxError):
                raise
            except Exception as exc:
                if plan.on_error == "fail_fast":
                    raise
                errors.append(
                    ExecutionStepError(
                        step_id=None,
                        operation=plan.destination.operation,
                        error_type=type(exc).__name__,
                        message="Destination failed",
                    )
                )
                _raise_if_cancelled(cancellation)
                return PlanExecutionResult(
                    status="failed",
                    outputs=(),
                    data=data,
                    include_data=False,
                    errors=tuple(errors),
                )
            _raise_if_cancelled(cancellation)

        return PlanExecutionResult(
            status="partial" if errors else "success",
            outputs=tuple(outputs),
            data=data,
            include_data=plan.destination is None,
            errors=tuple(errors),
        )


__all__ = ["ExecutePlanUseCase", "PlanExecutionError", "PlanExecutionResult"]
