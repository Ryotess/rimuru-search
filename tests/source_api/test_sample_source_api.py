from httpx import ASGITransport, AsyncClient

from examples.sample_source_api import app
from src.source_api.schemas import DocumentListResponse


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_sample_source_matches_ingestion_contract():
    async with await _client() as client:
        response = await client.get("/v1/documents", params={"page": 1, "limit": 2000})

    assert response.status_code == 200
    documents = DocumentListResponse.model_validate(response.json()["data"])
    assert len(documents.list) == 8
    assert documents.list[0].id == "guide-hybrid-search-001"
    assert documents.list[0].metadata["source"] == "generated-example"
    assert documents.meta.has_next_page is False


async def test_sample_source_returns_an_empty_page_after_the_data():
    async with await _client() as client:
        response = await client.get("/v1/documents", params={"page": 9, "limit": 1})

    assert response.status_code == 200
    assert response.json()["data"]["list"] == []


async def test_sample_source_validates_pagination_parameters():
    async with await _client() as client:
        response = await client.get("/v1/documents", params={"page": 0, "limit": 0})

    assert response.status_code == 422


async def test_sample_source_health_check():
    async with await _client() as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
