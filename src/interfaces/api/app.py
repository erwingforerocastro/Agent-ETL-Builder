"""FastAPI application factory."""

from fastapi import FastAPI

from application.use_cases.get_health import GetHealthUseCase
from interfaces.api.routes.health import create_health_router


def create_app(*, service_name: str, version: str) -> FastAPI:
    app = FastAPI(title=service_name, version=version)
    app.include_router(
        create_health_router(GetHealthUseCase(service_name=service_name, version=version))
    )
    return app
