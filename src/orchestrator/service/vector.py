# src/orchestrator/service/vector.py
import time
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import app_settings
from src.orchestrator.exceptions import OrchestratorException
from src.vector_search.service import ann_search_by_vector


async def fetch_vector_hits(
    session: AsyncSession,
    query_vector: list[float],
    top_k: int,
    document_ids: list[str] | None,
    metadata_filter: dict[str, Any] | None = None,
    collection: str = app_settings.document_default_collection,
) -> list[dict[str, Any]]:
    """
    Retrieve ANN hits for the query vector.
    """
    try:
        t0 = time.perf_counter()
        vector_hits = await ann_search_by_vector(
            session,
            query_vector,
            top_k,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
            collection=collection,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.bind(
            requested_top_k=top_k,
            returned_hits=len(vector_hits),
            filtered_ids=document_ids is not None,
            elapsed_ms=elapsed_ms,
        ).info("Vector search completed")
        return vector_hits
    except Exception as exc:
        logger.error("Vector search stage failed: {}", exc, exc_info=True)
        raise OrchestratorException("Vector search failed") from exc
