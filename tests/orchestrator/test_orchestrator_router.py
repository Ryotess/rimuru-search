from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.database import get_session
from src.orchestrator.router import router
from src.orchestrator.schemas import SearchDetailResponse


async def _fake_session():
    yield None


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = _fake_session
    return app


async def test_primary_search_route_returns_document_content():
    expected = SearchDetailResponse(query="hybrid", reranked_hits=[])
    with patch(
        "src.orchestrator.router.orchestrate_search",
        AsyncMock(return_value=expected),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            response = await client.post("/v1/search", json={"query": "hybrid"})

    assert response.status_code == 200
    assert response.json() == {
        "query": "hybrid",
        "collection": "default",
        "hits": [],
    }


async def test_details_route_remains_as_deprecated_alias():
    expected = SearchDetailResponse(query="hybrid", hits=[])
    with patch(
        "src.orchestrator.router.orchestrate_search_with_details",
        AsyncMock(return_value=expected),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            response = await client.post("/v1/search/details", json={"query": "hybrid"})

    assert response.status_code == 200
    assert response.json() == {
        "query": "hybrid",
        "collection": "default",
        "hits": [],
    }


async def test_demo_route_serves_the_bundled_ui():
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/v1/search/demo")

    assert response.status_code == 200
    assert "Rimuru Search Demo" in response.text
    assert 'fetch("/v1/search"' in response.text
    assert "${escapeHtml(hit.id)}" in response.text
    assert 'name="use_fuzzy" type="checkbox" checked' not in response.text
