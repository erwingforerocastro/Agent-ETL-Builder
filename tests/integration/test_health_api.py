import httpx
import pytest

from interfaces.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_health_endpoint_returns_service_metadata() -> None:
    app = create_app(service_name="test-service", version="1.2.3")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "test-service",
        "version": "1.2.3",
        "plan_generation": "disabled",
    }


async def test_health_reports_enabled_plan_generation() -> None:
    app = create_app(
        service_name="test-service",
        version="1.2.3",
        plan_generation="ollama",
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["plan_generation"] == "ollama"
