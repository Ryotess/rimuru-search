import httpx
import pytest

from src.source_api.exceptions import SourceApiClientError
from src.source_api.schemas import DocumentItem, DocumentListResponse, PaginationMeta
from src.source_api.service import iter_documents


class TestDocumentItem:
    def test_metadata_defaults_to_empty_dict(self):
        item = DocumentItem(
            id="document-1",
            content="A searchable document",
        )
        assert item.metadata == {}
        assert item.collection == "default"

    def test_model_fields(self):
        item = DocumentItem(
            collection="articles",
            id="article-42",
            content="A searchable document",
            metadata={"category": "article"},
        )
        assert item.id == "article-42"
        assert item.collection == "articles"
        assert item.content == "A searchable document"
        assert item.metadata == {"category": "article"}


class TestPaginationMeta:
    def test_fields(self):
        meta = PaginationMeta(
            page=1,
            take=100,
            itemCount=250,
            pageCount=3,
            hasPreviousPage=False,
            hasNextPage=True,
        )
        assert meta.page == 1
        assert meta.take == 100
        assert meta.item_count == 250
        assert meta.page_count == 3
        assert meta.has_previous_page is False
        assert meta.has_next_page is True


class TestDocumentListResponse:
    def test_parse(self):
        data = {
            "list": [
                {
                    "id": "document-1",
                    "content": "A searchable document",
                    "metadata": {"language": "en"},
                }
            ],
            "meta": {
                "page": 1,
                "take": 100,
                "itemCount": 1,
                "pageCount": 1,
                "hasPreviousPage": False,
                "hasNextPage": False,
            },
        }
        response = DocumentListResponse.model_validate(data)
        assert len(response.list) == 1
        assert response.list[0].content == "A searchable document"
        assert response.list[0].metadata == {"language": "en"}
        assert response.meta.has_next_page is False


class TestSourceApiSettings:
    def test_proxy_uses_unified_settings(self):
        from source_api.config import source_api_settings
        from src.config import app_settings

        assert app_settings.source_api_base_url == "http://localhost:3000"
        assert source_api_settings.base_url == app_settings.source_api_base_url
        assert source_api_settings.documents_path == "/v1/documents"


def _make_response(
    items: list[dict], page: int, page_count: int, has_next: bool
) -> dict:
    """Build a response matching the documented source API contract."""
    return {
        "status": "success",
        "code": 200,
        "data": {
            "list": items,
            "meta": {
                "page": page,
                "take": len(items),
                "itemCount": page_count * len(items),
                "pageCount": page_count,
                "hasPreviousPage": page > 1,
                "hasNextPage": has_next,
            },
        },
    }


class TestIterDocuments:
    @pytest.mark.asyncio
    async def test_multi_page_pagination(self, monkeypatch):
        """Pages are yielded until hasNextPage is false."""
        page1_items = [
            {
                "collection": "articles",
                "id": "document-1",
                "content": "First document",
                "metadata": {"page": 1},
            },
            {
                "id": "document-2",
                "content": "Second document",
            },
        ]
        page2_items = [
            {
                "id": "document-3",
                "content": "Third document",
            }
        ]
        calls: list[dict] = []

        async def mock_get(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            page = kwargs["params"]["page"]
            if page == 1:
                body = _make_response(page1_items, page=1, page_count=2, has_next=True)
            else:
                body = _make_response(page2_items, page=2, page_count=2, has_next=False)
            return httpx.Response(200, json=body, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        pages = [page async for page in iter_documents(page_size=2)]

        assert len(pages) == 2
        assert [call["params"]["page"] for call in calls] == [1, 2]
        assert all(call["url"].endswith("/v1/documents") for call in calls)
        assert pages[0][0]["content"] == "First document"
        assert pages[0][0]["collection"] == "articles"
        assert pages[0][0]["metadata"] == {"page": 1}
        assert pages[1][0]["content"] == "Third document"

    @pytest.mark.asyncio
    async def test_error_handling_non_200(self, monkeypatch):
        """A non-200 response raises a source API error."""

        async def mock_get(self, url, **kwargs):
            return httpx.Response(
                500, json={"error": "boom"}, request=httpx.Request("GET", url)
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        with pytest.raises(SourceApiClientError, match="500"):
            generator = iter_documents()
            await generator.__anext__()

    @pytest.mark.asyncio
    async def test_yielded_documents_include_default_metadata(self, monkeypatch):
        items = [
            {
                "id": "document-x",
                "content": "Example content",
            }
        ]

        async def mock_get(self, url, **kwargs):
            body = _make_response(items, page=1, page_count=1, has_next=False)
            return httpx.Response(200, json=body, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collected = []
        async for page in iter_documents():
            collected.extend(page)

        assert len(collected) == 1
        assert collected[0] == {
            "collection": "default",
            "id": "document-x",
            "content": "Example content",
            "metadata": {},
        }
