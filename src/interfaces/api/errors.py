"""Consistent API error envelope and exception handlers."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from domain.errors import (
    EtlError,
    PlanValidationError,
    RegistryError,
    RunAlreadyExistsError,
    RunApprovalRejectedError,
    RunApprovalTimeoutError,
    RunCancelledError,
    RunInvalidStateError,
    RunNotFoundError,
    RunPlanStaleError,
    SandboxError,
    WorkflowError,
)
from interfaces.api.schemas.runs import ErrorResponse

_LOGGER = logging.getLogger(__name__)

_CONFLICT_ERRORS = (
    RunAlreadyExistsError,
    RunInvalidStateError,
    RunApprovalRejectedError,
    RunApprovalTimeoutError,
    RunCancelledError,
    RunPlanStaleError,
)


def install_exception_handlers(app: FastAPI) -> None:
    """Install one error envelope for domain, validation, and unexpected errors."""

    @app.exception_handler(EtlError)
    async def _etl_error(_request: Request, exc: EtlError) -> JSONResponse:
        return _response(_status_for(exc), ErrorResponse.from_error(exc))

    @app.exception_handler(RequestValidationError)
    async def _request_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = {
            "errors": [
                {
                    "location": ".".join(str(part) for part in error.get("loc", ())),
                    "type": error.get("type", "value_error"),
                    "message": error.get("msg", "Invalid value"),
                }
                for error in exc.errors()
            ]
        }
        return _response(
            422,
            ErrorResponse(
                code="REQUEST_VALIDATION_FAILED",
                message="Request validation failed",
                details=details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return _response(
            exc.status_code,
            ErrorResponse(code=code, message=str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        _LOGGER.exception("Unhandled API exception", exc_info=exc)
        return _response(
            500,
            ErrorResponse(
                code="INTERNAL_ERROR",
                message="Internal server error",
            ),
        )


def _status_for(error: EtlError) -> int:
    if isinstance(error, RunNotFoundError):
        return 404
    if isinstance(error, _CONFLICT_ERRORS):
        return 409
    if isinstance(error, PlanValidationError):
        return 400
    if isinstance(error, (RegistryError, SandboxError)):
        return 500
    if isinstance(error, WorkflowError):
        return 500
    return 400


def _response(status_code: int, error: ErrorResponse) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json", exclude_none=True),
    )


__all__ = ["install_exception_handlers"]
