"""Embedding helpers for the seeding pipeline.

Moved from scripts/hybrid_db/seed.py to allow reuse and testability.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx
import numpy as np
from litellm import EmbeddingResponse, aembedding
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from numpy.typing import NDArray

from src.embedding.config import embedding_settings
from src.seeding.constants import MAX_EMBED_CONCURRENCY
from src.seeding.service.retry import retry_with_backoff


@asynccontextmanager
async def short_keepalive_client():
    """Create an AsyncHTTPHandler without persistent upstream connections.

    hosted_vllm embedding uses OpenAILikeEmbeddingHandler which expects AsyncHTTPHandler,
    not AsyncOpenAI. Passing this bypasses litellm's internal client cache.
    """
    timeout = httpx.Timeout(timeout=600.0, connect=5.0)
    handler = AsyncHTTPHandler(timeout=timeout)
    await handler.close()
    handler.client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=MAX_EMBED_CONCURRENCY,
            max_keepalive_connections=0,
        ),
        timeout=timeout,
        follow_redirects=True,
    )
    try:
        yield handler
    finally:
        await handler.close()


async def embed_batch(
    texts: list[str], client: AsyncHTTPHandler | None = None
) -> list[list[float]]:
    """Embed a list of strings, returning list of vectors.

    Wraps the LLM call with retry_with_backoff so transient timeouts and
    server errors are retried automatically.  On retry the timeout is
    extended to 120 s via a fresh httpx client.
    """
    kwargs: dict[str, Any] = {
        "model": embedding_settings.embedding_model,
        "input": texts,
        "api_base": embedding_settings.hosted_vllm_api_base,
    }
    if client is not None:
        kwargs["client"] = client

    async def _call() -> EmbeddingResponse:
        return await aembedding(**kwargs)

    embedding: EmbeddingResponse = await retry_with_backoff(
        _call, max_retries=3, base_delay=2.0, jitter_fraction=0.25
    )
    return [d["embedding"] for d in embedding.data]


async def embed_in_chunks(
    texts: list[str], batch_size: int, client: AsyncHTTPHandler | None = None
) -> NDArray[np.float32]:
    """Embed large text lists with bounded concurrency to distribute load across pods."""
    semaphore = asyncio.Semaphore(MAX_EMBED_CONCURRENCY)

    async def _embed_one(batch: list[str]) -> list[list[float]]:
        async with semaphore:
            return await embed_batch(batch, client=client)

    tasks = [
        _embed_one(texts[i : i + batch_size]) for i in range(0, len(texts), batch_size)
    ]
    results = await asyncio.gather(*tasks)
    all_vecs = [vec for batch_result in results for vec in batch_result]
    return np.asarray(all_vecs, dtype=np.float32)
