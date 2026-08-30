# src/reranker/service/rerank_docs.py
import time

from litellm import RerankResponse, arerank
from loguru import logger

from src.reranker.config import reranker_settings
from src.reranker.exceptions import RerankerException


async def aget_rerank_result(
    query: str,
    docs: list[str],
    top_n: int | None = None,
    instruction: str | None = None,
) -> RerankResponse:
    """
    Rerank input documents using the configured OpenAI-compatible scorer.

    The application sends raw (query, document) pairs. Model-specific prompt
    templates and score conversion belong to the model server configuration.
    """
    logger.debug(f"Start Reranker service function: {__name__}")
    if not docs:
        logger.warning("Rerank skipped: no documents provided")
        raise RerankerException("No documents provided to rerank.")

    effective_top_n = min(top_n or reranker_settings.top_n, len(docs))
    if effective_top_n < 1:
        raise RerankerException("top_n must be at least 1.")

    try:
        logger.bind(
            query_length=len(query),
            doc_count=len(docs),
            top_n=effective_top_n,
        ).debug("Requesting rerank scores")
        t0 = time.perf_counter()
        request_options = {"instruction": instruction} if instruction else {}
        rerank_result = await arerank(
            model=reranker_settings.reranker_model,
            query=query,
            documents=docs,
            top_n=effective_top_n,
            api_base=reranker_settings.hosted_vllm_api_base,
            **request_options,
        )
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.bind(
            returned=len(rerank_result.results),
            requested_top_n=effective_top_n,
            elapsed_ms=elapsed_ms,
        ).info("Rerank request completed")
        return rerank_result
    except Exception as e:
        logger.error(
            "Failed to rerank documents; upstream error type={}",
            type(e).__name__,
            exc_info=True,
        )
        raise RerankerException("Failed to rerank supplied documents") from e
