"""Unit tests for execution monitoring events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from application.ports.run_log import RunLogEntry
from application.ports.transform_log import TransformLogRow
from application.use_cases.execute_plan import ExecutePlanUseCase
from domain.entities.plan import (
    ExecutionPlan,
    PlanChunking,
    PlanDestination,
    PlanSource,
    PlanTransformation,
)
from domain.errors import TransformationError


@dataclass(frozen=True)
class _Frame:
    shape: tuple[int, int]


class _AcceptingValidator:
    def validate(self, plan: ExecutionPlan) -> None:
        del plan


class _Runner:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def run_source(self, operation: str, params: Mapping[str, object]) -> object:
        del operation, params
        return _Frame((2, 1))

    def run_transformation(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object:
        del operation, params, data
        if self._fail:
            raise TransformationError(
                code="TRANSFORMATION_FAILED",
                message="Transformation failed",
                module="test",
            )
        return _Frame((1, 1))

    def run_destination(
        self,
        operation: str,
        params: Mapping[str, object],
        data: object,
    ) -> object:
        del operation, params
        return {"saved": data}


class _RunLog:
    def __init__(self) -> None:
        self.items: list[RunLogEntry] = []

    def append(self, entry: RunLogEntry) -> None:
        self.items.append(entry)

    def entries(self, run_id: str) -> tuple[RunLogEntry, ...]:
        return tuple(entry for entry in self.items if entry.run_id == run_id)


class _TransformLog:
    def __init__(self) -> None:
        self.rows: list[TransformLogRow] = []

    def append(self, row: TransformLogRow) -> None:
        self.rows.append(row)


def _plan(*, on_error: str = "fail_fast") -> ExecutionPlan:
    return ExecutionPlan(
        plan_version="1.0",
        mode="pipeline",
        run_id="run-1",
        name="monitor_plan",
        description="Monitor a plan",
        source=PlanSource(operation="read_csv", params={"path": "input.csv"}),
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="trim_whitespace",
                params={"columns": ["name"]},
            ),
        ),
        destination=PlanDestination(operation="save_csv", params={"path": "output.csv"}),
        chunking=PlanChunking(enabled=False, size=1000),
        on_error=on_error,
        approval_required=True,
    )


def test_successful_execution_emits_events_and_transform_rows() -> None:
    run_log = _RunLog()
    transform_log = _TransformLog()
    use_case = ExecutePlanUseCase(
        _Runner(),
        _AcceptingValidator(),
        run_log=run_log,
        transform_log=transform_log,
    )

    result = use_case.execute(_plan(), run_id="run-1")

    assert result.status == "success"
    assert [entry.event for entry in run_log.items] == [
        "source_started",
        "source_finished",
        "step_started",
        "step_finished",
        "destination_started",
        "destination_finished",
    ]
    finished = next(entry for entry in run_log.items if entry.event == "step_finished")
    assert finished.step_id == "s1"
    assert finished.context == {"rows_in": 2, "rows_out": 1, "prev_step": None}
    assert finished.duration_ms is not None
    assert len(transform_log.rows) == 1
    row = transform_log.rows[0]
    assert row.step == "s1"
    assert row.prev_step == ""
    assert row.filename == "output.csv"
    assert row.result == {"status": "success", "rows_in": 2, "rows_out": 1}
    assert row.error is None


def test_failure_logs_the_error_and_transform_row() -> None:
    run_log = _RunLog()
    transform_log = _TransformLog()
    use_case = ExecutePlanUseCase(
        _Runner(fail=True),
        _AcceptingValidator(),
        run_log=run_log,
        transform_log=transform_log,
    )

    with pytest.raises(TransformationError):
        use_case.execute(_plan(), run_id="run-1")

    assert [entry.event for entry in run_log.items] == [
        "source_started",
        "source_finished",
        "step_started",
        "step_failed",
    ]
    failed = run_log.items[-1]
    assert failed.level == "error"
    assert failed.error is not None
    assert failed.error["code"] == "TRANSFORMATION_FAILED"
    assert len(transform_log.rows) == 1
    assert transform_log.rows[0].error is not None
    assert transform_log.rows[0].error["code"] == "TRANSFORMATION_FAILED"


def test_continue_policy_logs_failure_and_keeps_partial_result() -> None:
    run_log = _RunLog()
    transform_log = _TransformLog()
    use_case = ExecutePlanUseCase(
        _Runner(fail=True),
        _AcceptingValidator(),
        run_log=run_log,
        transform_log=transform_log,
    )

    result = use_case.execute(_plan(on_error="continue"), run_id="run-1")

    assert result.status == "partial"
    assert result.errors[0].step_id == "s1"
    assert [entry.event for entry in run_log.items] == [
        "source_started",
        "source_finished",
        "step_started",
        "step_failed",
        "destination_started",
        "destination_finished",
    ]
    assert transform_log.rows[0].error is not None


def test_execution_without_a_run_id_skips_monitoring() -> None:
    run_log = _RunLog()
    transform_log = _TransformLog()
    use_case = ExecutePlanUseCase(
        _Runner(),
        _AcceptingValidator(),
        run_log=run_log,
        transform_log=transform_log,
    )

    result = use_case.execute(_plan())

    assert result.status == "success"
    assert run_log.items == []
    assert transform_log.rows == []
