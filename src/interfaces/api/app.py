"""FastAPI application factory."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from application.use_cases.run_manager import RunManager
from interfaces.api.errors import install_exception_handlers
from interfaces.api.routes.health import create_health_router
from interfaces.api.routes.runs import create_run_router
from interfaces.api.schemas.runs import ErrorResponse


def create_app(
    *,
    service_name: str,
    version: str,
    run_manager: RunManager | None = None,
    max_request_bytes: int = 1_000_000,
    api_key: str | None = None,
    plan_generation: Literal["ollama", "disabled"] = "disabled",
    shutdown_callbacks: Sequence[Callable[[], None]] = (),
) -> FastAPI:
    if max_request_bytes <= 0:
        raise ValueError("max_request_bytes must be positive")
    if api_key is not None and not api_key.strip():
        raise ValueError("api_key must not be blank when provided")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        for callback in shutdown_callbacks:
            callback()

    app = FastAPI(title=service_name, version=version, lifespan=lifespan)
    install_exception_handlers(app)
    app.include_router(
        create_health_router(
            service_name=service_name,
            version=version,
            plan_generation=plan_generation,
        )
    )
    if run_manager is not None:
        app.include_router(create_run_router(run_manager))
        app.state.run_manager = run_manager

    @app.middleware("http")
    async def _protect_runs(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if (
            api_key is not None
            and request.url.path.startswith("/runs")
            and not hmac.compare_digest(
                request.headers.get("x-api-key", "").encode(),
                api_key.encode(),
            )
        ):
            return JSONResponse(
                status_code=401,
                content=ErrorResponse(
                    code="UNAUTHORIZED",
                    message="Missing or invalid API key",
                ).model_dump(mode="json", exclude_none=True),
            )
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                length = 0
            if length > max_request_bytes:
                return JSONResponse(
                    status_code=413,
                    content=ErrorResponse(
                        code="REQUEST_TOO_LARGE",
                        message="Request body exceeds the configured limit",
                    ).model_dump(mode="json", exclude_none=True),
                )
        return await call_next(request)

    return app


__all__ = ["create_app"]
