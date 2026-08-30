"""Tests for seed() retry behaviour around process_chunk."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _fake_client():
    """Stand-in for short_keepalive_client."""
    yield None


async def _one_chunk_iter(*args, **kwargs):
    """Async generator that yields a single chunk of fake rows."""
    yield [
        {"id": "document-1", "content": "First document", "metadata": {}},
        {"id": "document-2", "content": "Second document", "metadata": {}},
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

SEEDER = "src.seeding.service.seeder"


@pytest.fixture
def _patch_infra():
    """Patch iter_documents and short_keepalive_client for all tests."""
    with (
        patch(f"{SEEDER}.iter_documents", side_effect=_one_chunk_iter),
        patch(f"{SEEDER}.short_keepalive_client", side_effect=_fake_client),
    ):
        yield


@pytest.mark.usefixtures("_patch_infra")
class TestSeedRetry:
    """seed() should retry process_chunk on transient LLM errors."""

    async def test_seed_retries_process_chunk_on_retryable_error(self):
        """process_chunk raises Timeout once then succeeds → chunk processed."""
        mock_pc = AsyncMock(
            side_effect=[litellm.Timeout("test", "model", "provider"), 5]
        )

        with patch(f"{SEEDER}.process_chunk", mock_pc):
            from src.seeding.service.seeder import seed

            total = await seed(target_table="test_table")

        assert total == 5
        assert mock_pc.await_count == 2

    async def test_seed_raises_after_chunk_retries_exhausted(self):
        """process_chunk always raises Timeout → seed raises after retries."""
        mock_pc = AsyncMock(side_effect=litellm.Timeout("test", "model", "provider"))

        with patch(f"{SEEDER}.process_chunk", mock_pc):
            from src.seeding.service.seeder import seed

            with pytest.raises(litellm.Timeout):
                await seed(target_table="test_table")

    async def test_seed_no_retry_on_non_retryable_error(self):
        """process_chunk raises ValueError → raises immediately, no retry."""
        mock_pc = AsyncMock(side_effect=ValueError("bad data"))

        with patch(f"{SEEDER}.process_chunk", mock_pc):
            from src.seeding.service.seeder import seed

            with pytest.raises(ValueError, match="bad data"):
                await seed(target_table="test_table")

        assert mock_pc.await_count == 1

    async def test_seed_on_chunk_done_only_called_on_success(self):
        """process_chunk fails once then succeeds → on_chunk_done called once."""
        mock_pc = AsyncMock(
            side_effect=[litellm.Timeout("test", "model", "provider"), 3]
        )
        callback = MagicMock()

        with patch(f"{SEEDER}.process_chunk", mock_pc):
            from src.seeding.service.seeder import seed

            total = await seed(target_table="test_table", on_chunk_done=callback)

        assert total == 3
        callback.assert_called_once_with(1, 3)
