"""End-to-end API test using the real validator, executor, and sandbox."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

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
from infrastructure.logging.run_log import InMemoryRunLog
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


def _build_app(workspace: Path) -> tuple[FastAPI, _RecordingScheduler]:
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
    executor = ExecutePlanUseCase(RegistryStepRunner(registry, sandbox), validator)
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
        run_log=InMemoryRunLog(),
        scheduler=scheduler,
        clock=clock,
        cancellation_factory=EventCancellationToken,
    )
    return (
        create_app(service_name="test-service", version="1.0.0", run_manager=manager),
        scheduler,
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


def _assessment_payload(run_id: str) -> dict[str, object]:
    return {
        "plan_version": "1.0",
        "mode": "assessment",
        "run_id": run_id,
        "name": "assess",
        "description": "Assess the input",
        "source": {"operation": "read_csv", "params": {"path": "input.csv"}},
        "transformations": [],
        "destination": None,
        "chunking": {"enabled": True, "size": 1000},
        "on_error": "fail_fast",
        "approval_required": False,
    }


def _pipeline_payload(run_id: str) -> dict[str, object]:
    return {
        "plan_version": "1.0",
        "mode": "pipeline",
        "run_id": run_id,
        "name": "clean",
        "description": "Clean and write the input",
        "source": {"operation": "read_csv", "params": {"path": "input.csv"}},
        "transformations": [
            {
                "step_id": "s1",
                "operation": "trim_whitespace",
                "params": {"columns": ["name"]},
            }
        ],
        "destination": {"operation": "save_csv", "params": {"path": "output.csv"}},
        "chunking": {"enabled": True, "size": 1000},
        "on_error": "fail_fast",
        "approval_required": True,
    }


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_assessment_run_executes_through_real_stack(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("name\nAda\n", encoding="utf-8")
    app, scheduler = _build_app(tmp_path)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Assess", "plan": _assessment_payload("run-real-1")},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "ready"

    scheduler.run_all()

    status = (await _request(app, "GET", "/runs/run-real-1")).json()
    assert status["status"] == "succeeded"
    assert status["result"]["data_available"] is True
    assert status["plan"]["mode"] == "assessment"


@pytest.mark.anyio
async def test_pipeline_run_executes_transformations_and_loader(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("name\n Ada \nBob\n", encoding="utf-8")
    app, scheduler = _build_app(tmp_path)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Clean", "plan": _pipeline_payload("run-real-2")},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "awaiting_approval"

    approved = await _request(
        app,
        "POST",
        "/runs/run-real-2/approve",
        json={"approved": True},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "ready"

    scheduler.run_all()

    status = (await _request(app, "GET", "/runs/run-real-2")).json()
    assert status["status"] == "succeeded"
    assert status["result"]["status"] == "success"
    assert (tmp_path / "output.csv").exists()
    assert " Ada " not in (tmp_path / "output.csv").read_text(encoding="utf-8")

    logs = (await _request(app, "GET", "/runs/run-real-2/logs")).json()
    assert logs["logs"][-1]["event"] == "run_finished"
