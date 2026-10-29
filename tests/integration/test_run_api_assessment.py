"""Integration tests for source-only assessment through the run API."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from application.assessment.assess_source import AssessSourceUseCase
from application.registry.specs import MODULE_SPECS
from application.use_cases.execute_plan import ExecutePlanUseCase
from application.use_cases.profile_source import ProfileSourceUseCase
from application.use_cases.run_manager import RunManager
from application.use_cases.run_workflow_factory import RunWorkflowFactory
from application.validation.plan_validator import PlanValidator
from domain.entities.run import WorkflowLimits
from infrastructure.approval.in_memory import InMemoryApprovalGateway
from infrastructure.assessment.intake import AssessmentPlanIntakeFactory
from infrastructure.assessment.source_reader import WorkspaceSourceReader
from infrastructure.cancellation import EventCancellationToken
from infrastructure.cleanup.filesystem import FilesystemCleanup
from infrastructure.clock import SystemClock
from infrastructure.interpreter.registry_step_runner import RegistryStepRunner
from infrastructure.logging.run_log import InMemoryRunLog
from infrastructure.planning.submitted import SubmittedPlanIntakeFactory
from infrastructure.profiling.artifacts import FilesystemProfileWriter
from infrastructure.profiling.pandas_profiler import PandasChunkProfiler
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
    probe = FilesystemWorkspaceProbe(workspace)
    validator = PlanValidator(
        registry,
        workspace=probe,
        sizer=CanonicalPlanSizer(),
    )
    sandbox = SandboxExecutor(
        SandboxLimits(timeout_seconds=5, memory_mb=128),
        workspace=workspace,
    )
    executor = ExecutePlanUseCase(RegistryStepRunner(registry, sandbox), validator)
    profile_source = ProfileSourceUseCase(
        PandasChunkProfiler(),
        FilesystemProfileWriter(workspace / "artifacts"),
    )
    assessment = AssessSourceUseCase(WorkspaceSourceReader(probe), profile_source, sandbox=sandbox)
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
        assessment_intake_factory=AssessmentPlanIntakeFactory(assessment),
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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_source_only_run_assesses_confirms_and_writes_output(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text(
        "id,name,amount\n1,Ada,10\n2,Bob,\n2,Bob,\n",
        encoding="utf-8",
    )
    app, scheduler = _build_app(tmp_path)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={
            "message": "Assess this source",
            "run_id": "run-asm-1",
            "source": "input.csv",
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "awaiting_clarification"
    assert payload["next_action"] == "confirm"
    assert payload["assessment_id"] == "asm_run-asm-1"
    assert payload["assessment"]["row_count"] == 3
    assert payload["assessment"]["missing_inputs"] == ["destination"]
    assert payload["assessment"]["draft_plan"]["source_operation"] == "read_csv"
    assert any(
        step["operation"] == "drop_duplicate_rows"
        for step in payload["assessment"]["draft_plan"]["transformations"]
    )
    assert payload["questions"] == [
        "Review the assessment and confirm a destination for the draft plan."
    ]
    assert scheduler.tasks == []
    assert (tmp_path / "artifacts" / "run-asm-1").is_dir()

    confirmed = await _request(
        app,
        "POST",
        "/runs/run-asm-1/confirm",
        json={"destination": "output.csv"},
    )

    assert confirmed.status_code == 200
    confirmed_payload = confirmed.json()
    assert confirmed_payload["status"] == "awaiting_approval"
    assert confirmed_payload["next_action"] == "approve"
    assert confirmed_payload["plan"]["mode"] == "pipeline"
    assert confirmed_payload["plan"]["destination"]["operation"] == "save_csv"
    assert confirmed_payload["plan"]["destination"]["params"] == {"path": "output.csv"}

    approved = await _request(
        app,
        "POST",
        "/runs/run-asm-1/approve",
        json={"approved": True},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "ready"

    scheduler.run_all()

    final = (await _request(app, "GET", "/runs/run-asm-1")).json()
    assert final["status"] == "succeeded"
    assert final["result"]["status"] == "success"
    assert (tmp_path / "output.csv").exists()
    assert len((tmp_path / "output.csv").read_text(encoding="utf-8").splitlines()) == 3


@pytest.mark.anyio
async def test_assessment_confirmation_rejects_an_unsafe_destination(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("id\n1\n", encoding="utf-8")
    app, _ = _build_app(tmp_path)
    await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Assess", "run_id": "run-asm-2", "source": "input.csv"},
    )

    rejected = await _request(
        app,
        "POST",
        "/runs/run-asm-2/confirm",
        json={"destination": "../escape.csv"},
    )

    assert rejected.status_code == 400
    assert rejected.json()["code"] == "PLAN_PATH_TRAVERSAL"
    still_pending = (await _request(app, "GET", "/runs/run-asm-2")).json()
    assert still_pending["status"] == "awaiting_clarification"


@pytest.mark.anyio
async def test_explicit_assessment_mode_does_not_offer_confirmation(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("id\n1\n", encoding="utf-8")
    app, _ = _build_app(tmp_path)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={
            "message": "Assess only",
            "run_id": "run-asm-3",
            "mode": "assessment",
            "source": "input.csv",
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "awaiting_clarification"
    assert payload["next_action"] == "provide_plan"
    assert payload["assessment"]["assessment_id"] == "asm_run-asm-3"

    rejected = await _request(
        app,
        "POST",
        "/runs/run-asm-3/confirm",
        json={"destination": "output.csv"},
    )
    assert rejected.status_code == 409
