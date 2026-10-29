"""Health routes."""

from typing import Literal

from fastapi import APIRouter

from interfaces.api.schemas.health import HealthResponse


def create_health_router(
    *,
    service_name: str,
    version: str,
    plan_generation: Literal["ollama", "disabled"] = "disabled",
) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=service_name,
            version=version,
            plan_generation=plan_generation,
        )

    return router
