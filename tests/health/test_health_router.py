from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.health.router import router


async def _client() -> AsyncClient:
    app = FastAPI()
    app.include_router(router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_liveness_does_not_check_external_dependencies():
    async with await _client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


async def test_readiness_returns_200_when_dependencies_are_ready():
    result = {
        "status": "ready",
        "checks": {
            "database": "healthy",
            "embedding": "healthy",
            "reranker": "healthy",
            "redis": "disabled",
        },
    }
    with patch("src.health.router.get_readiness", AsyncMock(return_value=result)):
        async with await _client() as client:
            response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == result


async def test_readiness_returns_503_when_a_dependency_is_unhealthy():
    result = {
        "status": "not_ready",
        "checks": {
            "database": "healthy",
            "embedding": "unhealthy: ConnectError",
            "reranker": "healthy",
            "redis": "disabled",
        },
    }
    with patch("src.health.router.get_readiness", AsyncMock(return_value=result)):
        async with await _client() as client:
            response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == result
