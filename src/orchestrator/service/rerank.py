# src/orchestrator/service/rerank.py
from loguru import logger

from src.config import app_settings
from src.orchestrator.schemas import RerankedHit, RRFHit
from src.orchestrator.utils import apply_rerank_scores, build_rerank_documents
from src.reranker.config import reranker_settings
from src.reranker.exceptions import RerankerException
from src.reranker.service.rerank_docs import aget_rerank_result


async def rerank_candidates(
    query: str,
    candidates: list[RRFHit],
    requested_top_n: int | None,
) -> list[RerankedHit]:
    """Apply cross-encoder reranking to fused candidates."""
    if not candidates:
        logger.info("Rerank skipped: no fused candidates to rerank")
        return []

    rerank_top_n = min(requested_top_n or reranker_settings.top_n, len(candidates))

    def _fused_fallback() -> list[RerankedHit]:
        return [
            RerankedHit(**candidate.model_dump())
            for candidate in candidates[:rerank_top_n]
        ]

    if not app_settings.search_enable_rerank:
        logger.info("Reranking disabled by SEARCH_ENABLE_RERANK")
        return _fused_fallback()

    try:
        docs = build_rerank_documents(candidates)
        rerank_response = await aget_rerank_result(
            query=query, docs=docs, top_n=rerank_top_n
        )
        reranked_hits = apply_rerank_scores(candidates, rerank_response)
        logger.bind(candidates=len(candidates), reranked=len(reranked_hits)).info(
            "Rerank completed"
        )
        return reranked_hits or _fused_fallback()
    except RerankerException as exc:
        logger.warning(
            "Reranker unavailable, returning fused results without rerank: {}", exc
        )
        return _fused_fallback()
    except Exception as exc:
        logger.error("Rerank stage failed: {}", exc, exc_info=True)
        return _fused_fallback()
