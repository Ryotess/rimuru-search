import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import litellm
import numpy as np
import pytest

from src.seeding.service.embedding import (
    embed_batch,
    embed_in_chunks,
    short_keepalive_client,
)

MODULE = "src.seeding.service.embedding"


class TestEmbedBatch:
    """embed_batch returns list of vectors and passes correct kwargs."""

    async def test_returns_list_of_vectors(self):
        dim = 384
        fake_data = [{"embedding": [0.1] * dim}, {"embedding": [0.2] * dim}]
        mock_response = MagicMock()
        mock_response.data = fake_data

        with patch(
            f"{MODULE}.aembedding", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await embed_batch(["hello", "world"])

        assert len(result) == 2
        assert result[0] == [0.1] * dim
        assert result[1] == [0.2] * dim

    async def test_passes_correct_kwargs_without_client(self):
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [0.1]}]

        with patch(
            f"{MODULE}.aembedding", new_callable=AsyncMock, return_value=mock_response
        ) as mock_aembed:
            await embed_batch(["hello"])

        kwargs = mock_aembed.call_args.kwargs
        assert "model" in kwargs
        assert "input" in kwargs
        assert kwargs["input"] == ["hello"]
        assert "api_base" in kwargs
        assert "client" not in kwargs

    async def test_passes_client_when_provided(self):
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [0.1]}]
        fake_client = MagicMock()

        with patch(
            f"{MODULE}.aembedding", new_callable=AsyncMock, return_value=mock_response
        ) as mock_aembed:
            await embed_batch(["hello"], client=fake_client)

        kwargs = mock_aembed.call_args.kwargs
        assert kwargs["client"] is fake_client


class TestEmbedInChunks:
    """embed_in_chunks must call embed_batch concurrently with bounded semaphore."""

    async def test_concurrent_calls_bounded_by_semaphore(self):
        """With 12 batches and max_concurrency=3, at most 3 should run at once."""
        texts = [f"text_{i}" for i in range(3072)]
        dim = 384
        peak_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def mock_embed(batch, **kwargs):
            nonlocal peak_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                peak_concurrent = max(peak_concurrent, current_concurrent)
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return [[0.1] * dim for _ in batch]

        with (
            patch(f"{MODULE}.embed_batch", side_effect=mock_embed),
            patch(f"{MODULE}.MAX_EMBED_CONCURRENCY", 3),
        ):
            result = await embed_in_chunks(texts, 256)

        assert peak_concurrent > 1
        assert peak_concurrent <= 3
        assert result.shape == (3072, dim)
        assert result.dtype == np.float32

    async def test_result_order_preserved(self):
        """Embeddings must match input order even with concurrent execution."""
        texts = [f"text_{i}" for i in range(768)]
        dim = 384

        async def mock_embed(batch, **kwargs):
            results = []
            for t in batch:
                idx = int(t.split("_")[1])
                results.append([float(idx)] * dim)
            await asyncio.sleep(len(batch) * 0.0001)
            return results

        with (
            patch(f"{MODULE}.embed_batch", side_effect=mock_embed),
            patch(f"{MODULE}.MAX_EMBED_CONCURRENCY", 3),
        ):
            result = await embed_in_chunks(texts, 256)

        for i in range(768):
            assert result[i][0] == float(i)

    async def test_empty_input(self):
        """Empty input should return empty array."""
        with (
            patch(f"{MODULE}.embed_batch", new_callable=AsyncMock),
            patch(f"{MODULE}.MAX_EMBED_CONCURRENCY", 6),
        ):
            result = await embed_in_chunks([], 256)

        assert len(result) == 0

    async def test_single_batch(self):
        """Fewer texts than batch_size should produce a single batch call."""
        dim = 384

        async def mock_embed(batch, **kwargs):
            return [[0.1] * dim for _ in batch]

        with (
            patch(f"{MODULE}.embed_batch", side_effect=mock_embed),
            patch(f"{MODULE}.MAX_EMBED_CONCURRENCY", 6),
        ):
            result = await embed_in_chunks([f"t_{i}" for i in range(100)], 256)

        assert result.shape == (100, dim)


class TestShortKeepaliveClient:
    """short_keepalive_client yields an AsyncHTTPHandler with correct limits."""

    async def test_yields_handler(self):
        with patch(f"{MODULE}.MAX_EMBED_CONCURRENCY", 4):
            async with short_keepalive_client() as handler:
                assert handler is not None
                # Verify it is an AsyncHTTPHandler with an httpx.AsyncClient
                from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

                assert isinstance(handler, AsyncHTTPHandler)
                assert isinstance(handler.client, httpx.AsyncClient)

    async def test_handler_has_correct_timeout(self):
        with patch(f"{MODULE}.MAX_EMBED_CONCURRENCY", 4):
            async with short_keepalive_client() as handler:
                assert handler.client.timeout.connect == 5.0
                assert handler.client.timeout.read == 600.0


def _make_successful_response(n_texts=1, dim=384):
    """Helper to create a mock EmbeddingResponse."""
    mock_resp = MagicMock()
    mock_resp.data = [{"embedding": [0.1] * dim} for _ in range(n_texts)]
    return mock_resp


class TestEmbedBatchRetry:
    """embed_batch retries on transient errors using retry_with_backoff."""

    async def test_embed_batch_retries_on_timeout_then_succeeds(self):
        """Timeout twice then succeed -> 3 total calls."""
        success_resp = _make_successful_response(1)
        mock_aembed = AsyncMock(
            side_effect=[
                litellm.Timeout(message="timeout", model="test", llm_provider="vllm"),
                litellm.Timeout(message="timeout", model="test", llm_provider="vllm"),
                success_resp,
            ]
        )
        with (
            patch(f"{MODULE}.aembedding", mock_aembed),
            patch(f"{MODULE}.retry_with_backoff", wraps=_fast_retry),
        ):
            result = await embed_batch(["hello"])

        assert mock_aembed.call_count == 3
        assert len(result) == 1

    async def test_embed_batch_retries_on_internal_server_error(self):
        """InternalServerError once then succeed -> 2 total calls."""
        success_resp = _make_successful_response(1)
        mock_aembed = AsyncMock(
            side_effect=[
                litellm.InternalServerError(
                    message="error", model="test", llm_provider="vllm"
                ),
                success_resp,
            ]
        )
        with (
            patch(f"{MODULE}.aembedding", mock_aembed),
            patch(f"{MODULE}.retry_with_backoff", wraps=_fast_retry),
        ):
            result = await embed_batch(["hello"])

        assert mock_aembed.call_count == 2
        assert len(result) == 1

    async def test_embed_batch_retries_on_connect_error(self):
        """ConnectError once then succeed -> 2 total calls."""
        success_resp = _make_successful_response(1)
        mock_aembed = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                success_resp,
            ]
        )
        with (
            patch(f"{MODULE}.aembedding", mock_aembed),
            patch(f"{MODULE}.retry_with_backoff", wraps=_fast_retry),
        ):
            result = await embed_batch(["hello"])

        assert mock_aembed.call_count == 2
        assert len(result) == 1

    async def test_embed_batch_raises_after_retries_exhausted(self):
        """Always timeout -> raises after max retries."""
        mock_aembed = AsyncMock(
            side_effect=litellm.Timeout(
                message="timeout", model="test", llm_provider="vllm"
            )
        )
        with (
            patch(f"{MODULE}.aembedding", mock_aembed),
            patch(f"{MODULE}.retry_with_backoff", wraps=_fast_retry),
            pytest.raises(litellm.Timeout),
        ):
            await embed_batch(["hello"])

        # max_retries=3 means 4 total attempts (initial + 3 retries)
        assert mock_aembed.call_count == 4

    async def test_embed_batch_no_retry_on_non_retryable_error(self):
        """ValueError should raise immediately with only 1 call."""
        mock_aembed = AsyncMock(side_effect=ValueError("bad input"))
        with (
            patch(f"{MODULE}.aembedding", mock_aembed),
            patch(f"{MODULE}.retry_with_backoff", wraps=_fast_retry),
            pytest.raises(ValueError, match="bad input"),
        ):
            await embed_batch(["hello"])

        assert mock_aembed.call_count == 1


async def _fast_retry(fn, *, max_retries=3, base_delay=2.0, jitter_fraction=0.25):
    """A fast version of retry_with_backoff for tests (tiny delays)."""
    from src.seeding.service.retry import is_retryable

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(0.01)
    raise last_exc
