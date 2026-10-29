"""Health routes."""

from fastapi import APIRouter

from interfaces.api.schemas.health import HealthResponse


def create_health_router(*, service_name: str, version: str) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service=service_name, version=version)

    return router
