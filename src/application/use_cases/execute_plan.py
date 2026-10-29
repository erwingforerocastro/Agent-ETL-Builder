"""Execute a validated plan through an injected step runner."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter

from application.ports.cancellation import CancellationTokenPort
from application.ports.plan_validator import PlanValidatorPort
from application.ports.run_log import RunLogEntry, RunLogPort
from application.ports.step_runner import StepRunnerPort
from application.ports.transform_log import TransformLogPort, TransformLogRow
from application.use_cases.execution_result import ExecutionStepError, PlanExecutionResult
from domain.entities.plan import ExecutionPlan, PlanTransformation
from domain.errors import EtlError, RunCancelledError, SandboxError


class PlanExecutionError(Exception):
    """A validated plan could not be executed."""


def _raise_if_cancelled(cancellation: CancellationTokenPort | None) -> None:
    if cancellation is not None and cancellation.is_cancelled():
        raise RunCancelledError


def _row_count(value: object) -> int | None:
    shape = getattr(value, "shape", None)
    if isinstance(shape, tuple) and len(shape) == 2 and isinstance(shape[0], int):
        return shape[0]
    if isinstance(value, list | tuple):
        return len(value)
    return None


def _column_count(value: object) -> int | None:
    shape = getattr(value, "shape", None)
    if isinstance(shape, tuple) and len(shape) == 2 and isinstance(shape[1], int):
        return shape[1]
    return None


def _error_dict(exc: Exception) -> dict[str, object]:
    if isinstance(exc, EtlError):
        return exc.to_dict()
    return {
        "code": "EXECUTION_FAILED",
        "type": type(exc).__name__,
        "message": "Step failed",
        "retryable": False,
        "context": {},
    }


def _artifact_name(plan: ExecutionPlan) -> str:
    if plan.destination is not None:
        path = plan.destination.params.get("path")
        if isinstance(path, str) and path.strip():
            return path
    if plan.source is not None:
        path = plan.source.params.get("path")
        if isinstance(path, str) and path.strip():
            return path
    return ""


class ExecutePlanUseCase:
    """Orchestrates source, transformation, and destination steps."""

    def __init__(
        self,
        runner: StepRunnerPort,
        validator: PlanValidatorPort,
        *,
        run_log: RunLogPort | None = None,
        transform_log: TransformLogPort | None = None,
    ) -> None:
        self._runner = runner
        self._validator = validator
        self._run_log = run_log
        self._transform_log = transform_log

    def execute(
        self,
        plan: ExecutionPlan,
        *,
        cancellation: CancellationTokenPort | None = None,
        run_id: str | None = None,
    ) -> PlanExecutionResult:
        self._validator.validate(plan)
        _raise_if_cancelled(cancellation)

        errors: list[ExecutionStepError] = []
        data: object | None = None
        previous_step: str | None = None

        if plan.source is not None:
            started = perf_counter()
            self._event(
                run_id=run_id,
                event="source_started",
                module=plan.source.operation,
                status="running",
            )
            try:
                data = self._runner.run_source(plan.source.operation, plan.source.params)
            except Exception as exc:
                self._event(
                    run_id=run_id,
                    event="source_failed",
                    module=plan.source.operation,
                    status="failed",
                    duration_ms=_duration(started),
                    error=_error_dict(exc),
                )
                raise
            self._event(
                run_id=run_id,
                event="source_finished",
                module=plan.source.operation,
                status="success",
                duration_ms=_duration(started),
                context={"rows": _row_count(data), "columns": _column_count(data)},
            )
            _raise_if_cancelled(cancellation)

        for step in plan.transformations:
            if data is None:
                raise PlanExecutionError("No DataFrame available for transformation")
            _raise_if_cancelled(cancellation)
            rows_in = _row_count(data)
            started = perf_counter()
            self._event(
                run_id=run_id,
                event="step_started",
                module=step.operation,
                status="running",
                step_id=step.step_id,
                context={"rows_in": rows_in, "prev_step": previous_step},
            )
            try:
                data = self._runner.run_transformation(step.operation, step.params, data)
            except Exception as exc:
                self._step_failed(
                    plan=plan,
                    run_id=run_id,
                    step=step,
                    previous_step=previous_step,
                    rows_in=rows_in,
                    started=started,
                    exc=exc,
                )
                if isinstance(exc, RunCancelledError | SandboxError):
                    raise
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
            else:
                rows_out = _row_count(data)
                self._event(
                    run_id=run_id,
                    event="step_finished",
                    module=step.operation,
                    status="success",
                    step_id=step.step_id,
                    duration_ms=_duration(started),
                    context={
                        "rows_in": rows_in,
                        "rows_out": rows_out,
                        "prev_step": previous_step,
                    },
                )
                self._transform_row(
                    plan=plan,
                    run_id=run_id,
                    step=step,
                    previous_step=previous_step,
                    result={
                        "status": "success",
                        "rows_in": rows_in,
                        "rows_out": rows_out,
                    },
                    error=None,
                )
            previous_step = step.step_id
            _raise_if_cancelled(cancellation)

        outputs: list[object] = []
        if plan.destination is not None:
            if data is None:
                raise PlanExecutionError("No DataFrame available for destination")
            _raise_if_cancelled(cancellation)
            rows_in = _row_count(data)
            started = perf_counter()
            self._event(
                run_id=run_id,
                event="destination_started",
                module=plan.destination.operation,
                status="running",
                context={"rows_in": rows_in},
            )
            try:
                outputs.append(
                    self._runner.run_destination(
                        plan.destination.operation,
                        plan.destination.params,
                        data,
                    )
                )
            except Exception as exc:
                self._event(
                    run_id=run_id,
                    event="destination_failed",
                    module=plan.destination.operation,
                    status="failed",
                    duration_ms=_duration(started),
                    error=_error_dict(exc),
                    context={"rows_in": rows_in},
                )
                if isinstance(exc, RunCancelledError | SandboxError):
                    raise
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
            self._event(
                run_id=run_id,
                event="destination_finished",
                module=plan.destination.operation,
                status="success",
                duration_ms=_duration(started),
                context={"rows_in": rows_in},
            )
            _raise_if_cancelled(cancellation)

        return PlanExecutionResult(
            status="partial" if errors else "success",
            outputs=tuple(outputs),
            data=data,
            include_data=plan.destination is None,
            errors=tuple(errors),
        )

    def _step_failed(
        self,
        *,
        plan: ExecutionPlan,
        run_id: str | None,
        step: PlanTransformation,
        previous_step: str | None,
        rows_in: int | None,
        started: float,
        exc: Exception,
    ) -> None:
        error = _error_dict(exc)
        self._event(
            run_id=run_id,
            event="step_failed",
            module=step.operation,
            status="failed",
            step_id=step.step_id,
            duration_ms=_duration(started),
            error=error,
            context={"rows_in": rows_in, "prev_step": previous_step},
        )
        self._transform_row(
            plan=plan,
            run_id=run_id,
            step=step,
            previous_step=previous_step,
            result={"status": "failed", "rows_in": rows_in, "rows_out": None},
            error=error,
        )

    def _event(
        self,
        *,
        run_id: str | None,
        event: str,
        module: str,
        status: str,
        step_id: str | None = None,
        duration_ms: float | None = None,
        error: Mapping[str, object] | None = None,
        context: Mapping[str, object] | None = None,
    ) -> None:
        if run_id is None or self._run_log is None:
            return
        entry = RunLogEntry(
            timestamp=datetime.now(UTC),
            level="error" if error is not None else "info",
            run_id=run_id,
            event=event,
            status=status,
            step_id=step_id,
            module=module,
            duration_ms=duration_ms,
            error=error,
            context=context or {},
        )
        try:
            self._run_log.append(entry)
        except Exception:
            return

    def _transform_row(
        self,
        *,
        plan: ExecutionPlan,
        run_id: str | None,
        step: PlanTransformation,
        previous_step: str | None,
        result: Mapping[str, object],
        error: Mapping[str, object] | None,
    ) -> None:
        if run_id is None or self._transform_log is None:
            return
        row = TransformLogRow(
            run_id=run_id,
            filename=_artifact_name(plan),
            chunk="",
            prev_step=previous_step or "",
            step=step.step_id,
            date=datetime.now(UTC),
            result=result,
            error=error,
        )
        try:
            self._transform_log.append(row)
        except Exception:
            return


def _duration(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)


__all__ = ["ExecutePlanUseCase", "PlanExecutionError", "PlanExecutionResult"]
