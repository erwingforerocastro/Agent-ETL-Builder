"""Health routes."""

from fastapi import APIRouter

from application.use_cases.get_health import GetHealthUseCase
from interfaces.api.schemas.health import HealthResponse


def create_health_router(use_case: GetHealthUseCase) -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        status = use_case.execute()
        return HealthResponse(status=status.status, service=status.service, version=status.version)

    return router
