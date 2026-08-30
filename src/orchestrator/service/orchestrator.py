# src/orchestrator/service/orchestrator.py
import asyncio
import time

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache import get_cached, get_redis, set_cached
from src.orchestrator.schemas import (
    RerankedHit,
    SearchIdsResponse,
    SearchRequest,
    SearchResponse,
)
from src.orchestrator.service.embedding import generate_query_vector
from src.orchestrator.service.fusion import fuse_search_hits
from src.orchestrator.service.lexical import fetch_lexical_hits
from src.orchestrator.service.rerank import rerank_candidates
from src.orchestrator.service.vector import fetch_vector_hits

_background_tasks: set[asyncio.Task[None]] = set()


async def _run_search_pipeline(
    payload: SearchRequest, session: AsyncSession
) -> list[RerankedHit]:
    """
    Execute the hybrid search pipeline and return reranked hits with details.
    query -> embedding -> vector + lexical retrieval -> RRF fusion -> rerank
    """
    logger.bind(
        query_length=len(payload.query),
        collection=payload.collection,
        rrf_top_k=payload.rrf_top_k,
        rerank_top_n=payload.rerank_top_n,
        document_id_filters=len(payload.document_ids or []),
        has_metadata_filter=bool(payload.metadata_filter),
    ).info("Running search pipeline")

    t0 = time.perf_counter()

    query_vector = await generate_query_vector(payload.query)
    t_embed = time.perf_counter()

    vector_k = payload.vector_top_k or payload.rrf_top_k
    logger.bind(top_k=vector_k).debug("Fetching vector hits")
    vector_hits = await fetch_vector_hits(
        session,
        query_vector,
        vector_k,
        payload.document_ids,
        metadata_filter=payload.metadata_filter,
        collection=payload.collection,
    )
    t_vector = time.perf_counter()

    lexical_k = payload.lexical_top_k or payload.rrf_top_k
    logger.bind(top_k=lexical_k, use_fuzzy=payload.use_fuzzy).debug(
        "Fetching lexical hits"
    )
    lexical_hits = await fetch_lexical_hits(
        session,
        payload.query,
        lexical_k,
        payload.document_ids,
        use_fuzzy=payload.use_fuzzy,
        min_similarity=payload.min_similarity,
        metadata_filter=payload.metadata_filter,
        collection=payload.collection,
    )
    t_lexical = time.perf_counter()

    fused_hits = fuse_search_hits(vector_hits, lexical_hits, payload.rrf_top_k)
    t_fusion = time.perf_counter()

    reranked_hits = await rerank_candidates(
        query=payload.query,
        candidates=fused_hits,
        requested_top_n=payload.rerank_top_n,
    )
    t_rerank = time.perf_counter()

    logger.bind(
        total_hits=len(reranked_hits),
        total_ms=round((t_rerank - t0) * 1000, 1),
        embed_ms=round((t_embed - t0) * 1000, 1),
        vector_ms=round((t_vector - t_embed) * 1000, 1),
        lexical_ms=round((t_lexical - t_vector) * 1000, 1),
        fusion_ms=round((t_fusion - t_lexical) * 1000, 1),
        rerank_ms=round((t_rerank - t_fusion) * 1000, 1),
    ).info("Search pipeline completed")

    return reranked_hits


async def orchestrate_search(
    payload: SearchRequest, session: AsyncSession
) -> SearchResponse:
    """Return full search hits with an optional Redis cache wrapper."""
    redis_client = get_redis()

    if not payload.bypass_cache:
        cached = await get_cached(redis_client, payload)
        if cached is not None:
            logger.bind(
                query_length=len(payload.query), collection=payload.collection
            ).info("Cache hit")
            return cached

    reranked_hits = await _run_search_pipeline(payload, session)

    response = SearchResponse(
        query=payload.query,
        collection=payload.collection,
        hits=reranked_hits,
    )
    # Don't block the response on Redis SET; any failure is swallowed by set_cached.
    cache_task = asyncio.create_task(set_cached(redis_client, payload, response))
    _background_tasks.add(cache_task)
    cache_task.add_done_callback(_background_tasks.discard)
    return response


async def orchestrate_search_ids(
    payload: SearchRequest, session: AsyncSession
) -> SearchIdsResponse:
    """Compatibility endpoint for clients that only need ordered IDs."""
    redis_client = get_redis()

    if not payload.bypass_cache:
        cached = await get_cached(
            redis_client,
            payload,
            response_model=SearchIdsResponse,
            variant="ids",
        )
        if cached is not None:
            return cached

    reranked_hits = await _run_search_pipeline(payload, session)
    response = SearchIdsResponse(
        query=payload.query,
        collection=payload.collection,
        document_ids=[hit.id for hit in reranked_hits],
    )
    cache_task = asyncio.create_task(
        set_cached(redis_client, payload, response, variant="ids")
    )
    _background_tasks.add(cache_task)
    cache_task.add_done_callback(_background_tasks.discard)
    return response


# Source compatibility for integrations using the former function name.
orchestrate_search_with_details = orchestrate_search
