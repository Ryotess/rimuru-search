"""Tests for src.seeding.service.chunk_processor."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.models import Document
from src.seeding.constants import DB_BATCH_SIZE, EMBED_BATCH_SIZE
from src.seeding.service.chunk_processor import _resolve_target_table, process_chunk

# ---------------------------------------------------------------------------
# _resolve_target_table
# ---------------------------------------------------------------------------


class TestResolveTargetTable:
    def test_returns_document_table_for_default_name(self):
        table, is_default = _resolve_target_table(Document.__tablename__)
        assert table is Document.__table__
        assert is_default is True

    def test_returns_different_table_for_staging_name(self):
        table, is_default = _resolve_target_table("staging_documents")
        assert table is not Document.__table__
        assert table.name == "staging_documents"
        assert is_default is False


# ---------------------------------------------------------------------------
# process_chunk
# ---------------------------------------------------------------------------


class TestProcessChunk:
    @pytest.fixture()
    def fake_embeddings(self):
        """Return a factory that builds a numpy array of the requested size."""

        def _make(n: int) -> np.ndarray:
            return np.random.rand(n, 4).astype(np.float32)

        return _make

    async def test_returns_correct_inserted_count(self, fake_embeddings):
        rows = [
            {"id": "aaa", "content": "Document A", "metadata": {"key": "k1"}},
            {"id": "bbb", "content": "Document B", "metadata": {"key": "k2"}},
        ]
        embs = fake_embeddings(2)

        mock_session = AsyncMock()
        mock_session.add_all = MagicMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.seeding.service.chunk_processor.embed_in_chunks",
                new_callable=AsyncMock,
                return_value=embs,
            ),
            patch(
                "src.seeding.service.chunk_processor.SessionLocal",
                return_value=mock_session_ctx,
            ),
            patch("src.seeding.service.chunk_processor.gc"),
        ):
            count = await process_chunk(rows, Document.__tablename__)

        assert count == 2
        statement = mock_session.execute.await_args.args[0]
        assert "ON CONFLICT" in str(statement)
        assert "collection, id" in str(statement)

    async def test_skips_rows_with_missing_content(self, fake_embeddings):
        rows = [
            {"id": "aaa", "content": None, "metadata": {"key": "k1"}},
            {"id": "bbb", "content": "", "metadata": {"key": "k2"}},
            {"id": "ccc", "content": "  ", "metadata": {"key": "k3"}},
            {"id": "ddd", "content": "Valid", "metadata": {"key": "k4"}},
        ]
        embs = fake_embeddings(1)

        mock_session = AsyncMock()
        mock_session.add_all = MagicMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.seeding.service.chunk_processor.embed_in_chunks",
                new_callable=AsyncMock,
                return_value=embs,
            ),
            patch(
                "src.seeding.service.chunk_processor.SessionLocal",
                return_value=mock_session_ctx,
            ),
            patch("src.seeding.service.chunk_processor.gc"),
        ):
            count = await process_chunk(rows, Document.__tablename__)

        assert count == 1

    async def test_skips_rows_with_missing_id(self, fake_embeddings):
        rows = [
            {"id": None, "content": "Document A", "metadata": {"key": "k1"}},
            {"id": "bbb", "content": "Document B", "metadata": {"key": "k2"}},
        ]
        embs = fake_embeddings(1)

        mock_session = AsyncMock()
        mock_session.add_all = MagicMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.seeding.service.chunk_processor.embed_in_chunks",
                new_callable=AsyncMock,
                return_value=embs,
            ),
            patch(
                "src.seeding.service.chunk_processor.SessionLocal",
                return_value=mock_session_ctx,
            ),
            patch("src.seeding.service.chunk_processor.gc"),
        ):
            count = await process_chunk(rows, Document.__tablename__)

        assert count == 1

    async def test_calls_embed_in_chunks_with_correct_texts(self, fake_embeddings):
        rows = [
            {"id": "aaa", "content": "Alpha", "metadata": {"key": "k1"}},
            {"id": "bbb", "content": "Beta", "metadata": {"key": "k2"}},
        ]
        embs = fake_embeddings(2)

        mock_session = AsyncMock()
        mock_session.add_all = MagicMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.seeding.service.chunk_processor.embed_in_chunks",
                new_callable=AsyncMock,
                return_value=embs,
            ) as mock_embed,
            patch(
                "src.seeding.service.chunk_processor.SessionLocal",
                return_value=mock_session_ctx,
            ),
            patch("src.seeding.service.chunk_processor.gc"),
        ):
            await process_chunk(rows, Document.__tablename__, client=None)

        mock_embed.assert_awaited_once_with(
            ["Alpha", "Beta"], EMBED_BATCH_SIZE, client=None
        )

    async def test_inserts_in_batches(self, fake_embeddings):
        """When rows exceed DB_BATCH_SIZE, multiple commits happen."""
        n = DB_BATCH_SIZE + 1
        rows = [
            {
                "id": f"id-{i}",
                "content": f"Content {i}",
                "metadata": {"key": f"k{i}"},
            }
            for i in range(n)
        ]
        embs = fake_embeddings(n)

        mock_session = AsyncMock()
        mock_session.add_all = MagicMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.seeding.service.chunk_processor.embed_in_chunks",
                new_callable=AsyncMock,
                return_value=embs,
            ),
            patch(
                "src.seeding.service.chunk_processor.SessionLocal",
                return_value=mock_session_ctx,
            ),
            patch("src.seeding.service.chunk_processor.gc"),
        ):
            count = await process_chunk(rows, Document.__tablename__)

        assert count == n
        # One commit for the full batch, one for the remainder
        assert mock_session.commit.await_count == 2

    async def test_empty_rows_returns_zero(self):
        count = await process_chunk([], Document.__tablename__)
        assert count == 0

    async def test_calls_gc_collect_after_processing(self, fake_embeddings):
        rows = [{"id": "aaa", "content": "Document A", "metadata": {"key": "k1"}}]
        embs = fake_embeddings(1)

        mock_session = AsyncMock()
        mock_session.add_all = MagicMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "src.seeding.service.chunk_processor.embed_in_chunks",
                new_callable=AsyncMock,
                return_value=embs,
            ),
            patch(
                "src.seeding.service.chunk_processor.SessionLocal",
                return_value=mock_session_ctx,
            ),
            patch("src.seeding.service.chunk_processor.gc") as mock_gc,
        ):
            await process_chunk(rows, Document.__tablename__)

        mock_gc.collect.assert_called_once()
