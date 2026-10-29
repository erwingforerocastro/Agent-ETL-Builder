"""End-to-end monitoring tests for run JSONL and transform CSV logs."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from application.registry.specs import MODULE_SPECS
from application.use_cases.execute_plan import ExecutePlanUseCase
from application.use_cases.run_manager import RunManager
from application.use_cases.run_workflow_factory import RunWorkflowFactory
from application.validation.plan_validator import PlanValidator
from domain.entities.run import WorkflowLimits
from infrastructure.approval.in_memory import InMemoryApprovalGateway
from infrastructure.cancellation import EventCancellationToken
from infrastructure.cleanup.filesystem import FilesystemCleanup
from infrastructure.clock import SystemClock
from infrastructure.interpreter.registry_step_runner import RegistryStepRunner
from infrastructure.logging.jsonl import JsonlRunLog
from infrastructure.logging.run_log import InMemoryRunLog
from infrastructure.logging.transform_csv import CsvTransformLog
from infrastructure.planning.submitted import SubmittedPlanIntakeFactory
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.sandbox.executor import SandboxExecutor
from infrastructure.sandbox.limits import SandboxLimits
from infrastructure.state.run_checkpoint import InMemoryRunCheckpoint
from infrastructure.validation.path_probe import FilesystemWorkspaceProbe
from infrastructure.validation.plan_hasher import CanonicalPlanHasher
from infrastructure.validation.plan_parser import PydanticPlanParser
from infrastructure.validation.plan_sizer import CanonicalPlanSizer
from interfaces.api.app import create_app


class _RecordingScheduler:
    def __init__(self) -> None:
        self.tasks: list[Callable[[], None]] = []

    def submit(self, run_id: str, task: Callable[[], None]) -> None:
        del run_id
        self.tasks.append(task)

    def run_all(self) -> None:
        while self.tasks:
            self.tasks.pop(0)()


def _build_app(workspace: Path) -> tuple[FastAPI, _RecordingScheduler, InMemoryRunLog]:
    registry = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)
    validator = PlanValidator(
        registry,
        workspace=FilesystemWorkspaceProbe(workspace),
        sizer=CanonicalPlanSizer(),
    )
    sandbox = SandboxExecutor(
        SandboxLimits(timeout_seconds=5, memory_mb=128),
        workspace=workspace,
    )
    memory_log = InMemoryRunLog()
    run_log = JsonlRunLog(memory_log, logs_root=workspace / "logs")
    transform_log = CsvTransformLog(artifacts_root=workspace / "artifacts")
    executor = ExecutePlanUseCase(
        RegistryStepRunner(registry, sandbox),
        validator,
        run_log=run_log,
        transform_log=transform_log,
    )
    clock = SystemClock()
    checkpoints = InMemoryRunCheckpoint()
    scheduler = _RecordingScheduler()
    workflow_factory = RunWorkflowFactory(
        validator=validator,
        executor=executor,
        registry=registry,
        checkpoints=checkpoints,
        clock=clock,
        approvals=InMemoryApprovalGateway(clock),
        cleanup=FilesystemCleanup(workspace / "artifacts"),
        hasher=CanonicalPlanHasher(),
        limits=WorkflowLimits(approval_timeout_seconds=1, retry_backoff_seconds=0),
    )
    manager = RunManager(
        workflow_factory=workflow_factory,
        plan_parser=PydanticPlanParser(),
        validator=validator,
        intake_factory=SubmittedPlanIntakeFactory(),
        checkpoints=checkpoints,
        run_log=run_log,
        scheduler=scheduler,
        clock=clock,
        cancellation_factory=EventCancellationToken,
    )
    return (
        create_app(service_name="test-service", version="1.0.0", run_manager=manager),
        scheduler,
        memory_log,
    )


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    **kwargs: Any,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def _plan(run_id: str, *, columns: list[str] | None = None) -> dict[str, object]:
    return {
        "plan_version": "1.0",
        "mode": "pipeline",
        "run_id": run_id,
        "name": "monitored_plan",
        "description": "Exercise monitoring",
        "source": {"operation": "read_csv", "params": {"path": "input.csv"}},
        "transformations": [
            {
                "step_id": "s1",
                "operation": "trim_whitespace",
                "params": {"columns": columns or ["name"]},
            }
        ],
        "destination": {"operation": "save_csv", "params": {"path": "output.csv"}},
        "chunking": {"enabled": False, "size": 1000},
        "on_error": "fail_fast",
        "approval_required": True,
    }


async def _run(
    app: FastAPI,
    scheduler: _RecordingScheduler,
    run_id: str,
    *,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    created = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Run", "plan": _plan(run_id, columns=columns)},
    )
    assert created.status_code == 201
    approved = await _request(
        app,
        "POST",
        f"/runs/{run_id}/approve",
        json={"approved": True},
    )
    assert approved.status_code == 200
    scheduler.run_all()
    response = await _request(app, "GET", f"/runs/{run_id}")
    return cast(dict[str, Any], response.json())


@pytest.mark.anyio
async def test_successful_run_writes_jsonl_and_transform_csv(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("name\n Ada \n", encoding="utf-8")
    app, scheduler, _ = _build_app(tmp_path)

    body = await _run(app, scheduler, "run-monitor-1")

    assert body["status"] == "succeeded"
    log_lines = (tmp_path / "logs" / "run-monitor-1.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line)["event"] for line in log_lines]
    assert "run_created" in events
    assert "source_finished" in events
    assert "step_finished" in events
    assert "destination_finished" in events
    assert "run_finished" in events

    with (tmp_path / "artifacts" / "run-monitor-1" / "transform_log.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["Step"] == "s1"
    assert rows[0]["Filename"] == "output.csv"
    assert json.loads(rows[0]["Result"])["rows_out"] == 1

    logs = (await _request(app, "GET", "/runs/run-monitor-1/logs")).json()["logs"]
    assert any(entry["event"] == "step_finished" for entry in logs)


@pytest.mark.anyio
async def test_failed_run_preserves_transform_log_after_cleanup(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("name\n Ada \n", encoding="utf-8")
    app, scheduler, _ = _build_app(tmp_path)

    body = await _run(app, scheduler, "run-monitor-2", columns=["missing"])

    assert body["status"] == "failed"
    assert not (tmp_path / "output.csv").exists()
    transform_log = tmp_path / "artifacts" / "run-monitor-2" / "transform_log.csv"
    assert transform_log.exists()
    with transform_log.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["Step"] == "s1"
    assert json.loads(rows[0]["Error"])["code"]
