"""Run lifecycle routes."""

from typing import Any

from fastapi import APIRouter, Path

from application.use_cases.run_manager import RunCreateCommand, RunManager
from application.validation.constants import RUN_ID_PATTERN
from interfaces.api.schemas.runs import (
    ErrorResponse,
    RunApprovalRequest,
    RunConfirmRequest,
    RunCreateRequest,
    RunLogEntryResponse,
    RunLogsResponse,
    RunMessageRequest,
    RunResponse,
)

_RUN_ID = Path(
    ...,
    min_length=1,
    max_length=128,
    pattern=RUN_ID_PATTERN.pattern,
)

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


def create_run_router(run_manager: RunManager) -> APIRouter:
    """Build the run API around one process-local manager."""
    router = APIRouter(prefix="/runs", tags=["runs"])

    @router.post(
        "",
        response_model=RunResponse,
        status_code=201,
        responses=_ERROR_RESPONSES,
    )
    def create_run(request: RunCreateRequest) -> RunResponse:
        outcome = run_manager.create(
            RunCreateCommand(
                message=request.message,
                thread_id=request.thread_id,
                mode=request.mode,
                run_id=request.run_id,
                source=request.source,
                destination=request.destination,
                plan_payload=request.plan,
            )
        )
        return RunResponse.from_outcome(outcome)

    @router.get("/{run_id}", response_model=RunResponse, responses=_ERROR_RESPONSES)
    def get_run(run_id: str = _RUN_ID) -> RunResponse:
        return RunResponse.from_outcome(run_manager.outcome(run_id))

    @router.post(
        "/{run_id}/approve",
        response_model=RunResponse,
        responses=_ERROR_RESPONSES,
    )
    def approve_run(
        request: RunApprovalRequest,
        run_id: str = _RUN_ID,
    ) -> RunResponse:
        return RunResponse.from_outcome(run_manager.approve(run_id, request.approved))

    @router.post(
        "/{run_id}/confirm",
        response_model=RunResponse,
        responses=_ERROR_RESPONSES,
    )
    def confirm_run(
        request: RunConfirmRequest,
        run_id: str = _RUN_ID,
    ) -> RunResponse:
        return RunResponse.from_outcome(run_manager.confirm(run_id, request.destination))

    @router.post(
        "/{run_id}/messages",
        response_model=RunResponse,
        responses=_ERROR_RESPONSES,
    )
    def message_run(
        request: RunMessageRequest,
        run_id: str = _RUN_ID,
    ) -> RunResponse:
        return RunResponse.from_outcome(
            run_manager.message(
                run_id,
                request.message,
                source=request.source,
                destination=request.destination,
            )
        )

    @router.post(
        "/{run_id}/cancel",
        response_model=RunResponse,
        responses=_ERROR_RESPONSES,
    )
    def cancel_run(run_id: str = _RUN_ID) -> RunResponse:
        return RunResponse.from_outcome(run_manager.cancel(run_id))

    @router.get(
        "/{run_id}/logs",
        response_model=RunLogsResponse,
        responses=_ERROR_RESPONSES,
    )
    def get_run_logs(run_id: str = _RUN_ID) -> RunLogsResponse:
        return RunLogsResponse(
            run_id=run_id,
            logs=[RunLogEntryResponse.from_entry(entry) for entry in run_manager.logs(run_id)],
        )

    return router


__all__ = ["create_run_router"]
