#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from typing import Any

from litellm.llms.custom_httpx.async_client_cleanup import close_litellm_async_clients

from src.config import app_settings
from src.embedding.service import encode_query
from src.logging_config import shutdown_logging
from src.orchestrator.utils import extract_embedding_vector
from src.reranker.service.rerank_docs import aget_rerank_result


def _value(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def validate_rerank_order(response: Any) -> tuple[float, float]:
    """Return relevant/irrelevant scores and reject a reversed scorer."""
    scores = {
        int(_value(result, "index")): float(_value(result, "relevance_score"))
        for result in getattr(response, "results", [])
    }
    if set(scores) != {0, 1}:
        raise RuntimeError("reranker did not return scores for both smoke documents")
    if scores[0] <= scores[1]:
        raise RuntimeError(
            "reranker smoke check failed: the relevant document did not score higher"
        )
    return scores[0], scores[1]


async def _run_checks() -> None:
    embedding = await encode_query("How does hybrid search combine retrieval methods?")
    vector = extract_embedding_vector(embedding)
    if len(vector) != app_settings.vdb_embedding_dim:
        raise RuntimeError(
            f"embedding dimension mismatch: got {len(vector)}, "
            f"expected {app_settings.vdb_embedding_dim}"
        )
    print(f"OK embedding model: dimension={len(vector)}")

    if not app_settings.search_enable_rerank:
        print("SKIP reranker model: SEARCH_ENABLE_RERANK=false")
        return

    response = await aget_rerank_result(
        query="What is the capital of France?",
        docs=[
            "Paris is the capital and most populous city of France.",
            "Bananas are berries produced by several kinds of flowering plants.",
        ],
        top_n=2,
    )
    relevant, irrelevant = validate_rerank_order(response)
    print(
        "OK reranker model: "
        f"relevant_score={relevant:.6f} irrelevant_score={irrelevant:.6f}"
    )


async def main() -> None:
    try:
        await _run_checks()
    finally:
        await close_litellm_async_clients()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutdown_logging()
