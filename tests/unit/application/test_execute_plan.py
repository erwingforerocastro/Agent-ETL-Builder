"""Unit tests for the execute-plan use case."""

from collections.abc import Mapping
from typing import cast

import pytest

from application.use_cases.execute_plan import ExecutePlanUseCase, PlanExecutionError
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from domain.errors import RunCancelledError, SandboxError


class _AcceptingValidator:
    def __init__(self) -> None:
        self.plans: list[ExecutionPlan] = []

    def validate(self, plan: ExecutionPlan) -> None:
        self.plans.append(plan)


class _RejectingValidator:
    def validate(self, plan: ExecutionPlan) -> None:
        raise ValueError("invalid plan")


class _RecordingRunner:
    def __init__(
        self,
        *,
        fail_transformation: bool = False,
        fail_destination: bool = False,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail_transformation = fail_transformation
        self._fail_destination = fail_destination

    def run_source(self, operation: str, params: Mapping[str, object]) -> object:
        self.calls.append(("source", operation))
        return {"value": 1}

    def run_transformation(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object:
        self.calls.append(("transformation", operation))
        if self._fail_transformation:
            raise RuntimeError("transformation failed")
        current = cast(Mapping[str, int], data)
        return {"value": current["value"] + 1}

    def run_destination(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object:
        self.calls.append(("destination", operation))
        if self._fail_destination:
            raise RuntimeError("destination failed")
        return {"saved": data}


def _plan(
    *,
    destination: bool = True,
    on_error: str = "fail_fast",
) -> ExecutionPlan:
    return ExecutionPlan(
        plan_version="1.0",
        mode="pipeline" if destination else "assessment",
        run_id="1729850000000-a1b2c3d4",
        name="test_plan",
        description="A test plan",
        source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"]},
            ),
        ),
        destination=(
            PlanDestination(operation="save_csv", params={"path": "output.csv"})
            if destination
            else None
        ),
        chunking=PlanChunking(enabled=True, size=1000),
        on_error=on_error,
        approval_required=destination,
    )


class _CancellingRunner(_RecordingRunner):
    def run_transformation(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object:
        self.calls.append(("transformation", operation))
        raise RunCancelledError()


class _SandboxFailingRunner(_RecordingRunner):
    def run_transformation(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object:
        self.calls.append(("transformation", operation))
        raise SandboxError(
            code="SANDBOX_TIMEOUT",
            message="timed out",
            module="test",
        )


def test_execute_plan_validates_before_running() -> None:
    runner = _RecordingRunner()
    validator = _AcceptingValidator()
    plan = _plan()

    ExecutePlanUseCase(runner, validator).execute(plan)

    assert validator.plans == [plan]


def test_execute_plan_does_not_run_when_validation_fails() -> None:
    runner = _RecordingRunner()

    with pytest.raises(ValueError, match="invalid plan"):
        ExecutePlanUseCase(runner, _RejectingValidator()).execute(_plan())

    assert runner.calls == []


def test_execute_plan_runs_steps_in_order() -> None:
    runner = _RecordingRunner()

    result = ExecutePlanUseCase(runner, _AcceptingValidator()).execute(_plan())

    assert runner.calls == [
        ("source", "read_csv"),
        ("transformation", "trim_whitespace"),
        ("destination", "save_csv"),
    ]
    assert result.status == "success"
    assert result.outputs == ({"saved": {"value": 2}},)
    assert "dataframe" not in result.to_dict()


def test_execute_plan_returns_data_for_assessment() -> None:
    runner = _RecordingRunner()

    result = ExecutePlanUseCase(runner, _AcceptingValidator()).execute(_plan(destination=False))

    assert result.to_dict() == {
        "status": "success",
        "outputs": [],
        "dataframe": {"value": 2},
    }


def test_execute_plan_fail_fast_reraises_transformation_error() -> None:
    runner = _RecordingRunner(fail_transformation=True)

    with pytest.raises(RuntimeError, match="transformation failed"):
        ExecutePlanUseCase(runner, _AcceptingValidator()).execute(_plan())


def test_execute_plan_continue_skips_failed_transformation() -> None:
    runner = _RecordingRunner(fail_transformation=True)

    result = ExecutePlanUseCase(runner, _AcceptingValidator()).execute(_plan(on_error="continue"))

    assert runner.calls == [
        ("source", "read_csv"),
        ("transformation", "trim_whitespace"),
        ("destination", "save_csv"),
    ]
    assert result.outputs == ({"saved": {"value": 1}},)
    assert result.status == "partial"
    assert result.errors[0].step_id == "s1"
    assert result.errors[0].error_type == "RuntimeError"


def test_execute_plan_continue_marks_destination_failure() -> None:
    runner = _RecordingRunner(fail_destination=True)

    result = ExecutePlanUseCase(runner, _AcceptingValidator()).execute(_plan(on_error="continue"))

    assert result.status == "failed"
    assert result.outputs == ()
    assert result.errors[0].operation == "save_csv"
    assert result.errors[0].message == "Destination failed"


def test_execute_plan_continue_does_not_swallow_cancellation() -> None:
    runner = _CancellingRunner()

    with pytest.raises(RunCancelledError):
        ExecutePlanUseCase(runner, _AcceptingValidator()).execute(_plan(on_error="continue"))


def test_execute_plan_does_not_swallow_sandbox_errors_with_continue() -> None:
    runner = _SandboxFailingRunner()

    with pytest.raises(SandboxError, match="timed out"):
        ExecutePlanUseCase(runner, _AcceptingValidator()).execute(_plan(on_error="continue"))


def test_execute_plan_fail_fast_reraises_destination_error() -> None:
    runner = _RecordingRunner(fail_destination=True)

    with pytest.raises(RuntimeError, match="destination failed"):
        ExecutePlanUseCase(runner, _AcceptingValidator()).execute(_plan())


def test_execute_plan_requires_data_for_transformations() -> None:
    plan = ExecutionPlan(
        plan_version="1.0",
        mode="assessment",
        run_id="1729850000000-a1b2c3d4",
        name="test_plan",
        description="A test plan",
        source=None,
        transformations=(PlanTransformation(step_id="s1", operation="trim_whitespace", params={}),),
        destination=None,
        chunking=PlanChunking(enabled=True, size=1000),
        on_error="fail_fast",
        approval_required=False,
    )

    with pytest.raises(PlanExecutionError, match="No DataFrame"):
        ExecutePlanUseCase(_RecordingRunner(), _AcceptingValidator()).execute(plan)
