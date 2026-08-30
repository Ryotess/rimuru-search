# src/orchestrator/service/lexical.py
import time
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import app_settings
from src.lexical_search.exceptions import LexicalSearchException
from src.lexical_search.service import lexical_search_by_content
from src.orchestrator.exceptions import OrchestratorException


async def fetch_lexical_hits(
    session: AsyncSession,
    query: str,
    top_k: int,
    document_ids: list[str] | None,
    use_fuzzy: bool,
    min_similarity: float | None,
    metadata_filter: dict[str, Any] | None = None,
    collection: str = app_settings.document_default_collection,
) -> list[dict[str, Any]]:
    """
    Retrieve hits from the configured lexical backend.
    """
    try:
        t0 = time.perf_counter()
        lexical_hits = await lexical_search_by_content(
            session,
            query,
            top_k,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
            use_fuzzy=use_fuzzy,
            min_similarity=min_similarity,
            collection=collection,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.bind(
            requested_top_k=top_k,
            returned_hits=len(lexical_hits),
            filtered_ids=document_ids is not None,
            use_fuzzy=use_fuzzy,
            elapsed_ms=elapsed_ms,
        ).info("Lexical search completed")
        return lexical_hits
    except LexicalSearchException as exc:
        logger.error("Lexical search stage failed: {}", exc, exc_info=True)
        raise OrchestratorException("Lexical search failed") from exc
    except Exception as exc:
        logger.error("Lexical search stage failed unexpectedly: {}", exc, exc_info=True)
        raise OrchestratorException("Lexical search failed") from exc
