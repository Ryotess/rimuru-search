"""Tests for src.seeding.service.seeder – the top-level seed() orchestrator."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

MODULE = "src.seeding.service.seeder"


@asynccontextmanager
async def _fake_client_ctx():
    """Stand-in for short_keepalive_client that yields a simple MagicMock."""
    yield MagicMock(name="fake_http_handler")


class TestSeed:
    """seed() should iterate via iter_documents, process each chunk, and report totals."""

    async def test_calls_iter_documents_with_rows_per_chunk(self):
        """seed() must call iter_documents with page_size=ROWS_PER_CHUNK."""
        from src.seeding.constants import ROWS_PER_CHUNK

        call_args = {}

        async def fake_iter(page_size, start_page=1):
            call_args["page_size"] = page_size
            yield [{"id": "1", "content": "Electricity", "metadata": {"key": "elec"}}]

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", new_callable=AsyncMock, return_value=1),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            await seed()

        assert call_args["page_size"] == ROWS_PER_CHUNK

    async def test_passes_rows_to_process_chunk_with_correct_args(self):
        """Rows from iter_documents must be forwarded to process_chunk with table and client."""
        batch1 = [{"id": "1", "content": "A", "metadata": {"key": "a"}}]
        batch2 = [{"id": "2", "content": "B", "metadata": {"key": "b"}}]

        async def fake_iter(page_size, start_page=1):
            yield batch1
            yield batch2

        mock_process = AsyncMock(return_value=1)

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", mock_process),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            await seed()

        assert mock_process.call_count == 2
        calls = mock_process.call_args_list
        assert calls[0].args[0] == batch1
        assert calls[1].args[0] == batch2
        for call in calls:
            assert "client" in call.kwargs

    async def test_returns_correct_total_rows(self):
        """seed() must return the sum of rows inserted across all chunks."""

        async def fake_iter(page_size, start_page=1):
            yield [{"id": "1", "content": "A", "metadata": {"key": "a"}}]
            yield [{"id": "2", "content": "B", "metadata": {"key": "b"}}]

        mock_process = AsyncMock(side_effect=[3, 5])

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", mock_process),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            result = await seed()

        assert result == 8

    async def test_calls_on_chunk_done_callback(self):
        """seed() must call on_chunk_done(chunk_index, rows_inserted) for each chunk."""

        async def fake_iter(page_size, start_page=1):
            yield [{"id": "1", "content": "A", "metadata": {"key": "a"}}]
            yield [{"id": "2", "content": "B", "metadata": {"key": "b"}}]

        mock_process = AsyncMock(side_effect=[3, 5])
        callback = MagicMock()

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", mock_process),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            await seed(on_chunk_done=callback)

        assert callback.call_count == 2
        callback.assert_any_call(1, 3)
        callback.assert_any_call(2, 5)

    async def test_works_without_callback(self):
        """seed() must work fine when on_chunk_done is None (default)."""

        async def fake_iter(page_size, start_page=1):
            yield [{"id": "1", "content": "A", "metadata": {"key": "a"}}]

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", new_callable=AsyncMock, return_value=1),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            result = await seed()

        assert result == 1

    async def test_uses_default_table_name_when_none(self):
        """When target_table is None, seed() should use DEFAULT_TARGET_TABLE."""

        async def fake_iter(page_size, start_page=1):
            yield [{"id": "1", "content": "A", "metadata": {"key": "a"}}]

        mock_process = AsyncMock(return_value=1)

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", mock_process),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            await seed(target_table=None)

        assert mock_process.call_args_list[0].args[1] == "documents"

    async def test_uses_custom_table_name_when_provided(self):
        """When target_table is given, seed() should pass it to process_chunk."""

        async def fake_iter(page_size, start_page=1):
            yield [{"id": "1", "content": "A", "metadata": {"key": "a"}}]

        mock_process = AsyncMock(return_value=1)

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", mock_process),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            await seed(target_table="my_custom_table")

        assert mock_process.call_args_list[0].args[1] == "my_custom_table"

    async def test_live_seed_invalidates_search_cache(self):
        async def fake_iter(page_size, start_page=1):
            yield [{"id": "1", "content": "A", "metadata": {}}]

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", new_callable=AsyncMock, return_value=1),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
            patch(f"{MODULE}.get_redis", return_value=MagicMock()),
            patch(
                f"{MODULE}.invalidate_search_cache", new_callable=AsyncMock
            ) as invalidate,
        ):
            from src.seeding.service.seeder import seed

            await seed()

        invalidate.assert_awaited_once()

    async def test_staging_seed_does_not_invalidate_search_cache(self):
        async def fake_iter(page_size, start_page=1):
            yield [{"id": "1", "content": "A", "metadata": {}}]

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", new_callable=AsyncMock, return_value=1),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
            patch(
                f"{MODULE}.invalidate_search_cache", new_callable=AsyncMock
            ) as invalidate,
        ):
            from src.seeding.service.seeder import seed

            await seed(target_table="documents_staging")

        invalidate.assert_not_awaited()

    async def test_start_chunk_passes_correct_start_page(self):
        """start_chunk=N causes iter_documents to start at page N+1."""

        call_args = {}

        async def fake_iter(page_size, start_page=1):
            call_args["start_page"] = start_page
            yield [{"id": "1", "content": "A", "metadata": {"key": "a"}}]

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", new_callable=AsyncMock, return_value=1),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            await seed(start_chunk=5)

        assert call_args["start_page"] == 6

    async def test_start_chunk_offsets_chunk_idx(self):
        """Chunk index reported to on_chunk_done starts from start_chunk+1."""

        async def fake_iter(page_size, start_page=1):
            yield [{"id": "1", "content": "A", "metadata": {"key": "a"}}]

        callback = MagicMock()

        with (
            patch(f"{MODULE}.iter_documents", fake_iter),
            patch(f"{MODULE}.process_chunk", new_callable=AsyncMock, return_value=10),
            patch(f"{MODULE}.short_keepalive_client", _fake_client_ctx),
        ):
            from src.seeding.service.seeder import seed

            await seed(start_chunk=3, on_chunk_done=callback)

        callback.assert_called_once_with(4, 10)
