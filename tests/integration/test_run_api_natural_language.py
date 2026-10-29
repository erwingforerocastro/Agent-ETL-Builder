"""End-to-end API tests for natural-language plan intake."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI

from application.planning.intake import NaturalLanguagePlanIntakeFactory
from application.planning.models import SourceSchema
from application.ports.plan_synthesizer import ConversationTurn
from application.registry.specs import MODULE_SPECS
from application.use_cases.execute_plan import ExecutePlanUseCase
from application.use_cases.run_manager import RunManager
from application.use_cases.run_workflow_factory import RunWorkflowFactory
from application.validation.plan_validator import PlanValidator
from domain.entities.plan import PlanTransformation
from domain.entities.plan_draft import PlanDraft
from domain.entities.run import PlanRequest, WorkflowLimits
from domain.errors import PlanSynthesisError, PlanValidationError
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


class _FakeSynthesizer:
    def __init__(self, drafts: Sequence[PlanDraft]) -> None:
        self._drafts = list(drafts)
        self.calls: list[
            tuple[
                PlanRequest,
                tuple[ConversationTurn, ...],
                PlanValidationError | None,
                SourceSchema | None,
            ]
        ] = []

    def synthesize(
        self,
        request: PlanRequest,
        *,
        history: Sequence[ConversationTurn] = (),
        previous_error: PlanValidationError | None = None,
        source_schema: SourceSchema | None = None,
    ) -> PlanDraft:
        self.calls.append((request, tuple(history), previous_error, source_schema))
        if not self._drafts:
            raise PlanSynthesisError(
                code="PLAN_SYNTHESIS_UNAVAILABLE",
                message="The plan builder is unavailable",
                module="test",
                retryable=True,
            )
        return self._drafts.pop(0)


def _draft() -> PlanDraft:
    return PlanDraft(
        name="clean_names",
        description="Remove duplicates and trim names.",
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="drop_duplicate_rows",
                params={},
            ),
            PlanTransformation(
                step_id="s2",
                operation="trim_whitespace",
                params={},
            ),
        ),
    )


def _build_app(
    workspace: Path,
    synthesizer: _FakeSynthesizer,
) -> tuple[FastAPI, _RecordingScheduler]:
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
    parser = PydanticPlanParser()
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
        plan_parser=parser,
        validator=validator,
        intake_factory=SubmittedPlanIntakeFactory(),
        checkpoints=checkpoints,
        run_log=InMemoryRunLog(),
        scheduler=scheduler,
        clock=clock,
        cancellation_factory=EventCancellationToken,
        nl_intake_factory=NaturalLanguagePlanIntakeFactory(
            synthesizer=synthesizer,
            parser=parser,
        ),
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


@pytest.mark.anyio
async def test_natural_language_request_builds_and_executes_a_plan(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("name\n Ada \nBob\n Ada \n", encoding="utf-8")
    synthesizer = _FakeSynthesizer([_draft()])
    app, scheduler = _build_app(tmp_path, synthesizer)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={
            "run_id": "run-nl-1",
            "message": "Remove duplicates and trim names",
            "source": "input.csv",
            "destination": "output.json",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "awaiting_approval"
    assert body["plan"]["source"] == {
        "operation": "read_csv",
        "params": {"path": "input.csv"},
    }
    assert body["plan"]["destination"] == {
        "operation": "save_json",
        "params": {"path": "output.json"},
    }

    approved = await _request(
        app,
        "POST",
        "/runs/run-nl-1/approve",
        json={"approved": True},
    )
    assert approved.status_code == 200
    scheduler.run_all()

    status = (await _request(app, "GET", "/runs/run-nl-1")).json()
    assert status["status"] == "succeeded"
    output = pd.read_json(tmp_path / "output.json", orient="records")
    assert output["name"].tolist() == ["Ada", "Bob"]


@pytest.mark.anyio
async def test_natural_language_clarification_can_continue_with_a_message(
    tmp_path: Path,
) -> None:
    (tmp_path / "input.csv").write_text("name\n Ada \nBob\n Ada \n", encoding="utf-8")
    synthesizer = _FakeSynthesizer([_draft()])
    app, scheduler = _build_app(tmp_path, synthesizer)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={
            "run_id": "run-nl-2",
            "message": "Clean this file",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "awaiting_clarification"
    assert body["next_action"] == "clarify"
    assert body["missing_inputs"] == ["source", "destination"]

    continued = await _request(
        app,
        "POST",
        "/runs/run-nl-2/messages",
        json={
            "message": "Use input.csv and output.json",
            "source": "input.csv",
            "destination": "output.json",
        },
    )

    assert continued.status_code == 200
    assert continued.json()["status"] == "awaiting_approval"

    approved = await _request(
        app,
        "POST",
        "/runs/run-nl-2/approve",
        json={"approved": True},
    )
    assert approved.status_code == 200
    scheduler.run_all()

    status = (await _request(app, "GET", "/runs/run-nl-2")).json()
    assert status["status"] == "succeeded"
    assert (tmp_path / "output.json").exists()


@pytest.mark.anyio
async def test_invalid_draft_is_repaired_from_the_validation_error(
    tmp_path: Path,
) -> None:
    (tmp_path / "input.csv").write_text("name\nAda\n", encoding="utf-8")
    invalid = PlanDraft(
        name="bad_plan",
        description="Use an unknown operation.",
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="drop_everything",
                params={},
            ),
        ),
    )
    synthesizer = _FakeSynthesizer([invalid, _draft()])
    app, _ = _build_app(tmp_path, synthesizer)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={
            "run_id": "run-nl-repair",
            "message": "Remove duplicates and trim names",
            "source": "input.csv",
            "destination": "output.json",
        },
    )

    assert created.status_code == 201
    assert created.json()["status"] == "awaiting_approval"
    assert len(synthesizer.calls) == 2
    previous_error = synthesizer.calls[1][2]
    assert isinstance(previous_error, PlanValidationError)
    assert previous_error.code == "PLAN_UNKNOWN_OPERATION"


@pytest.mark.anyio
async def test_unrepairable_draft_terminates_after_the_attempt_limit(
    tmp_path: Path,
) -> None:
    (tmp_path / "input.csv").write_text("name\nAda\n", encoding="utf-8")
    invalid = PlanDraft(
        name="bad_plan",
        description="Use an unknown operation.",
        transformations=(
            PlanTransformation(
                step_id="s1",
                operation="drop_everything",
                params={},
            ),
        ),
    )
    synthesizer = _FakeSynthesizer([invalid, invalid, invalid])
    app, _ = _build_app(tmp_path, synthesizer)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={
            "run_id": "run-nl-unrepairable",
            "message": "Remove duplicates",
            "source": "input.csv",
            "destination": "output.json",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "PLAN_UNKNOWN_OPERATION"
    assert len(synthesizer.calls) == 3


@pytest.mark.anyio
async def test_blank_follow_up_message_is_rejected(tmp_path: Path) -> None:
    app, _ = _build_app(tmp_path, _FakeSynthesizer([]))

    response = await _request(
        app,
        "POST",
        "/runs/run-nl-blank/messages",
        json={"message": "   "},
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_message_after_terminal_failure_is_a_conflict(tmp_path: Path) -> None:
    (tmp_path / "input.csv").write_text("name\nAda\n", encoding="utf-8")
    synthesizer = _FakeSynthesizer([])
    app, _ = _build_app(tmp_path, synthesizer)

    created = await _request(
        app,
        "POST",
        "/runs",
        json={
            "run_id": "run-nl-3",
            "message": "Clean names",
            "source": "input.csv",
            "destination": "output.json",
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "failed"
    assert created.json()["error"]["code"] == "PLAN_SYNTHESIS_UNAVAILABLE"

    response = await _request(
        app,
        "POST",
        "/runs/run-nl-3/messages",
        json={"message": "Try again"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "RUN_INVALID_STATE"
