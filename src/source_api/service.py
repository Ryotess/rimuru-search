from collections.abc import AsyncGenerator
from typing import Any

import httpx
from loguru import logger

from src.source_api.config import source_api_settings
from src.source_api.exceptions import SourceApiClientError
from src.source_api.schemas import DocumentListResponse


def _base_url() -> str:
    return source_api_settings.base_url.rstrip("/")


async def iter_documents(
    page_size: int = 5000,
    start_page: int = 1,
) -> AsyncGenerator[list[dict[str, Any]]]:
    """Paginate through documents from the configured source API.

    Each document contains a ``collection``, string ``id``, searchable
    ``content``, and arbitrary JSON ``metadata``.
    """
    page = start_page

    async with httpx.AsyncClient() as client:
        while True:
            path = "/" + source_api_settings.documents_path.strip("/")
            url = f"{_base_url()}{path}"
            logger.bind(page=page, limit=page_size).debug("Fetching document page")

            response = await client.get(url, params={"page": page, "limit": page_size})
            if response.status_code != 200:
                raise SourceApiClientError(
                    f"Source API returned status {response.status_code}"
                )

            body = response.json()
            if "data" not in body:
                raise SourceApiClientError(
                    f"Source API response missing 'data' key: {list(body.keys())}"
                )
            data = DocumentListResponse.model_validate(body["data"])

            items: list[dict[str, Any]] = [
                {
                    "collection": item.collection,
                    "id": item.id,
                    "content": item.content,
                    "metadata": item.metadata,
                }
                for item in data.list
            ]

            logger.debug(
                "Received {} items on page {} (hasNextPage={})",
                len(items),
                page,
                data.meta.has_next_page,
            )

            yield items

            if not data.meta.has_next_page:
                break
            page += 1
