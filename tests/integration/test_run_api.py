"""Integration tests for the run API and background workflow wiring."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from application.ports.cancellation import CancellationTokenPort
from application.ports.cleanup import CleanupResult
from application.ports.plan_validator import PlanValidatorPort
from application.registry.specs import MODULE_SPECS
from application.use_cases.execution_result import PlanExecutionResult
from application.use_cases.run_manager import RunManager
from application.use_cases.run_workflow_factory import RunWorkflowFactory
from domain.entities.plan import ExecutionPlan
from domain.entities.run import ApprovalState, CleanupPolicy, WorkflowLimits
from domain.errors import PlanValidationError
from infrastructure.cancellation import EventCancellationToken
from infrastructure.logging.run_log import InMemoryRunLog
from infrastructure.planning.submitted import SubmittedPlanIntakeFactory
from infrastructure.registry.bindings import MODULE_FUNCTIONS
from infrastructure.registry.module_registry import build_module_registry
from infrastructure.state.run_checkpoint import InMemoryRunCheckpoint
from infrastructure.validation.plan_hasher import CanonicalPlanHasher
from infrastructure.validation.plan_parser import PydanticPlanParser
from interfaces.api.app import create_app

REGISTRY = build_module_registry(MODULE_SPECS, MODULE_FUNCTIONS)


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 1, tzinfo=UTC)
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        self._monotonic += 0.01
        return self._monotonic

    def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class _Approval:
    def __init__(self, decision: ApprovalState | None = None) -> None:
        self.decision = decision
        self.decisions: list[tuple[str, ApprovalState]] = []

    def request(
        self,
        run_id: str,
        *,
        timeout_seconds: float,
        cancellation: CancellationTokenPort,
    ) -> ApprovalState:
        del run_id, timeout_seconds
        if cancellation.is_cancelled():
            return ApprovalState.CANCELLED
        return self.decision or ApprovalState.TIMED_OUT

    def decide(self, run_id: str, decision: ApprovalState) -> None:
        self.decisions.append((run_id, decision))
        self.decision = decision


class _Cleanup:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CleanupPolicy]] = []

    def apply(self, run_id: str, policy: CleanupPolicy) -> CleanupResult:
        self.calls.append((run_id, policy))
        return CleanupResult(
            policy=policy,
            removed=(run_id,) if policy is CleanupPolicy.CLEANUP else (),
        )


class _AcceptingValidator:
    def validate(self, plan: ExecutionPlan) -> None:
        del plan


class _RejectingValidator:
    def validate(self, plan: ExecutionPlan) -> None:
        del plan
        raise PlanValidationError(
            code="PLAN_UNSAFE_OPERATION",
            message="Plan is not allowed",
            module="test",
        )


class _Executor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(
        self,
        plan: ExecutionPlan,
        *,
        cancellation: CancellationTokenPort | None = None,
        run_id: str | None = None,
    ) -> PlanExecutionResult:
        del plan, cancellation, run_id
        self.calls += 1
        return PlanExecutionResult(status="success", outputs=())


class _RecordingScheduler:
    def __init__(self) -> None:
        self.tasks: list[Callable[[], None]] = []

    def submit(self, run_id: str, task: Callable[[], None]) -> None:
        del run_id
        self.tasks.append(task)

    def run_all(self) -> None:
        while self.tasks:
            self.tasks.pop(0)()


def _plan_payload(
    *,
    run_id: str = "run-api-1",
    mode: str = "assessment",
    approval_required: bool = False,
) -> dict[str, object]:
    destination = (
        {"operation": "save_csv", "params": {"path": "output.csv"}} if mode == "pipeline" else None
    )
    return {
        "plan_version": "1.0",
        "mode": mode,
        "run_id": run_id,
        "name": "api_plan",
        "description": "API test plan",
        "source": {"operation": "read_csv", "params": {"path": "input.csv"}},
        "transformations": [],
        "destination": destination,
        "chunking": {"enabled": True, "size": 1000},
        "on_error": "fail_fast",
        "approval_required": approval_required,
    }


def _build_manager(
    *,
    approval: _Approval | None = None,
    executor: _Executor | None = None,
    validator: PlanValidatorPort | None = None,
    limits: WorkflowLimits | None = None,
) -> tuple[RunManager, _RecordingScheduler, InMemoryRunCheckpoint]:
    clock = _Clock()
    checkpoints = InMemoryRunCheckpoint()
    scheduler = _RecordingScheduler()
    run_validator = validator or _AcceptingValidator()
    workflow_factory = RunWorkflowFactory(
        validator=run_validator,
        executor=executor or _Executor(),
        registry=REGISTRY,
        checkpoints=checkpoints,
        clock=clock,
        approvals=approval or _Approval(),
        cleanup=_Cleanup(),
        hasher=CanonicalPlanHasher(),
        limits=limits
        or WorkflowLimits(
            approval_timeout_seconds=1,
            retry_backoff_seconds=0,
        ),
    )
    manager = RunManager(
        workflow_factory=workflow_factory,
        plan_parser=PydanticPlanParser(),
        validator=run_validator,
        intake_factory=SubmittedPlanIntakeFactory(),
        checkpoints=checkpoints,
        run_log=InMemoryRunLog(),
        scheduler=scheduler,
        clock=clock,
        cancellation_factory=EventCancellationToken,
    )
    return manager, scheduler, checkpoints


def _app(
    manager: RunManager,
    *,
    max_request_bytes: int = 1_000_000,
    api_key: str | None = None,
) -> FastAPI:
    return create_app(
        service_name="test-service",
        version="1.0.0",
        run_manager=manager,
        max_request_bytes=max_request_bytes,
        api_key=api_key,
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
async def test_create_assessment_run_and_execute_in_background() -> None:
    manager, scheduler, _ = _build_manager()
    app = _app(manager)

    response = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Assess this", "plan": _plan_payload()},
    )

    assert response.status_code == 201
    created = response.json()
    assert created["run_id"] == "run-api-1"
    assert created["status"] == "ready"
    assert created["next_action"] == "wait"
    assert created["plan"]["mode"] == "assessment"
    assert len(scheduler.tasks) == 1

    scheduler.run_all()

    status = (await _request(app, "GET", "/runs/run-api-1")).json()
    assert status["status"] == "succeeded"
    assert status["result"]["status"] == "success"
    assert status["next_action"] == "none"

    logs = (await _request(app, "GET", "/runs/run-api-1/logs")).json()
    events = [entry["event"] for entry in logs["logs"]]
    assert "run_created" in events
    assert "run_started" in events
    assert "run_finished" in events


@pytest.mark.anyio
async def test_pipeline_requires_approval_then_runs() -> None:
    manager, scheduler, _ = _build_manager()
    app = _app(manager)

    created = (
        await _request(
            app,
            "POST",
            "/runs",
            json={"message": "Write output", "plan": _plan_payload(mode="pipeline")},
        )
    ).json()
    assert created["status"] == "awaiting_approval"
    assert created["next_action"] == "approve"
    assert scheduler.tasks == []

    approved = (
        await _request(
            app,
            "POST",
            "/runs/run-api-1/approve",
            json={"approved": True},
        )
    ).json()
    assert approved["status"] == "ready"
    assert len(scheduler.tasks) == 1

    scheduler.run_all()
    final = (await _request(app, "GET", "/runs/run-api-1")).json()
    assert final["status"] == "succeeded"


@pytest.mark.anyio
async def test_rejection_and_cancellation_are_terminal() -> None:
    manager, scheduler, _ = _build_manager()
    app = _app(manager)

    await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Write output", "plan": _plan_payload(mode="pipeline")},
    )
    rejected = (
        await _request(
            app,
            "POST",
            "/runs/run-api-1/approve",
            json={"approved": False},
        )
    ).json()
    assert rejected["status"] == "rejected"
    assert scheduler.tasks == []

    await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Assess this", "plan": _plan_payload(run_id="run-api-2")},
    )
    cancelled = (await _request(app, "POST", "/runs/run-api-2/cancel")).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["approval_state"] == "not_required"

    scheduler.run_all()
    logs = (await _request(app, "GET", "/runs/run-api-2/logs")).json()
    events = [entry["event"] for entry in logs["logs"]]
    assert "run_started" not in events
    assert "cancellation_requested" in events


@pytest.mark.anyio
async def test_plan_only_request_is_accepted() -> None:
    manager, scheduler, _ = _build_manager()
    app = _app(manager)

    response = await _request(
        app,
        "POST",
        "/runs",
        json={"plan": _plan_payload(run_id="plan-only-run")},
    )

    assert response.status_code == 201
    assert response.json()["run_id"] == "plan-only-run"
    assert len(scheduler.tasks) == 1


@pytest.mark.anyio
async def test_message_only_run_awaits_a_plan() -> None:
    manager, scheduler, _ = _build_manager()
    app = _app(manager)

    response = await _request(app, "POST", "/runs", json={"message": "Do something"})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "awaiting_clarification"
    assert body["next_action"] == "clarify"
    assert body["questions"]
    assert "AGENT_ETL_OLLAMA_MODEL" in body["questions"][0]
    assert scheduler.tasks == []


@pytest.mark.anyio
async def test_empty_plan_is_rejected_with_a_clear_message() -> None:
    manager, _, _ = _build_manager()
    app = _app(manager)

    response = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Do something", "plan": {}},
    )

    assert response.status_code == 422
    assert "plan must not be empty" in response.text


@pytest.mark.anyio
async def test_duplicate_run_id_and_invalid_state_conflict() -> None:
    manager, _, _ = _build_manager()
    app = _app(manager)

    await _request(app, "POST", "/runs", json={"message": "Assess", "plan": _plan_payload()})
    duplicate = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Assess again", "plan": _plan_payload()},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "RUN_ALREADY_EXISTS"

    invalid = await _request(
        app,
        "POST",
        "/runs/run-api-1/approve",
        json={"approved": True},
    )
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "RUN_INVALID_STATE"


@pytest.mark.anyio
async def test_openapi_exposes_run_contract() -> None:
    manager, _, _ = _build_manager()
    app = _app(manager)

    response = await _request(app, "GET", "/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/runs" in paths
    assert "/runs/{run_id}" in paths
    assert "/runs/{run_id}/approve" in paths
    assert "/runs/{run_id}/cancel" in paths
    assert "/runs/{run_id}/logs" in paths


@pytest.mark.anyio
async def test_unknown_run_and_logs_return_404_envelope() -> None:
    manager, _, _ = _build_manager()
    app = _app(manager)

    missing = await _request(app, "GET", "/runs/missing")
    missing_logs = await _request(app, "GET", "/runs/missing/logs")
    missing_approval = await _request(
        app,
        "POST",
        "/runs/missing/approve",
        json={"approved": True},
    )
    missing_cancel = await _request(app, "POST", "/runs/missing/cancel")

    assert missing.status_code == 404
    assert missing.json() == {
        "code": "RUN_NOT_FOUND",
        "message": "Run was not found",
        "retryable": False,
        "details": {"run_id": "missing"},
    }
    assert missing_logs.status_code == 404
    assert missing_approval.status_code == 404
    assert missing_cancel.status_code == 404


@pytest.mark.anyio
async def test_invalid_plan_returns_domain_error_envelope() -> None:
    manager, _, _ = _build_manager()
    app = _app(manager)

    response = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Bad plan", "plan": {"plan_version": "1.0"}},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "PLAN_INVALID_SCHEMA"
    assert body["retryable"] is False
    assert body["details"]["errors"]


@pytest.mark.anyio
async def test_plan_is_validated_before_run_creation() -> None:
    manager, _, checkpoints = _build_manager(validator=_RejectingValidator())
    app = _app(manager)

    response = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Rejected plan", "plan": _plan_payload(run_id="rejected-run")},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "PLAN_UNSAFE_OPERATION"
    assert checkpoints.get("rejected-run") is None


@pytest.mark.anyio
async def test_request_validation_and_size_limits_use_envelope() -> None:
    manager, _, _ = _build_manager()
    app = _app(manager, max_request_bytes=100)

    invalid = await _request(app, "POST", "/runs", json={})
    too_large = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "x" * 500},
    )

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "REQUEST_VALIDATION_FAILED"
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "REQUEST_TOO_LARGE"


@pytest.mark.anyio
async def test_optional_api_key_protects_run_routes() -> None:
    manager, _, _ = _build_manager()
    app = _app(manager, api_key="secret-key")

    unauthorized = await _request(app, "POST", "/runs", json={"message": "Assess"})
    authorized = await _request(
        app,
        "POST",
        "/runs",
        json={"message": "Assess", "plan": _plan_payload()},
        headers={"X-API-Key": "secret-key"},
    )
    health = await _request(app, "GET", "/health")

    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "UNAUTHORIZED"
    assert authorized.status_code == 201
    assert health.status_code == 200


@pytest.mark.anyio
async def test_plan_identity_mismatch_is_rejected() -> None:
    manager, _, _ = _build_manager()
    app = _app(manager)
    payload = _plan_payload(run_id="plan-run", mode="pipeline")

    response = await _request(
        app,
        "POST",
        "/runs",
        json={
            "message": "Mismatch",
            "run_id": "request-run",
            "mode": "pipeline",
            "plan": payload,
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "PLAN_RUN_ID_MISMATCH"
