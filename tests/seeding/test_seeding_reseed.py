from unittest.mock import AsyncMock, MagicMock, patch

from src.seeding.service.reseed import (
    BACKUP_TABLE,
    MAIN_TABLE,
    STAGING_TABLE,
    ensure_extensions,
    rebuild_indexes,
    recreate_staging,
    reseed,
    swap_tables,
)


def _mock_engine_begin():
    """Return (mock_engine, mock_conn) where engine.begin() is an async context manager."""
    mock_conn = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx
    return mock_engine, mock_conn


def _mock_engine_connect():
    """Return (mock_engine, mock_conn) where engine.connect() is an async context manager."""
    mock_conn = AsyncMock()
    # execution_options is async in SQLAlchemy 2.0.44+ — must be awaited
    mock_conn.execution_options = AsyncMock(return_value=mock_conn)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_ctx
    return mock_engine, mock_conn


class TestEnsureExtensions:
    async def test_executes_five_statements(self):
        mock_engine, mock_conn = _mock_engine_begin()

        with patch("src.seeding.service.reseed.engine", mock_engine):
            await ensure_extensions()

        assert mock_conn.execute.call_count == 5
        sqls = [str(c[0][0].text) for c in mock_conn.execute.call_args_list]
        assert any("vector" in s for s in sqls)
        assert any("unaccent" in s and "WITH SCHEMA public" in s for s in sqls)
        assert any("pg_trgm" in s for s in sqls)
        assert any("pg_textsearch" in s for s in sqls)
        assert any("immutable_unaccent" in s for s in sqls)


class TestRecreateStaging:
    async def test_executes_drop_create_and_collection_primary_key(self):
        mock_engine, mock_conn = _mock_engine_begin()

        with patch("src.seeding.service.reseed.engine", mock_engine):
            await recreate_staging("documents", "documents_staging")

        assert mock_conn.execute.call_count == 3
        drop_sql = str(mock_conn.execute.call_args_list[0][0][0].text)
        create_sql = str(mock_conn.execute.call_args_list[1][0][0].text)
        primary_key_sql = str(mock_conn.execute.call_args_list[2][0][0].text)
        assert "DROP TABLE" in drop_sql
        assert "documents_staging" in drop_sql
        assert "CREATE TABLE" in create_sql
        assert "LIKE" in create_sql
        assert "PRIMARY KEY (collection, id)" in primary_key_sql


class TestSwapTables:
    async def test_executes_lock_renames_primary_keys_and_drops_backup(self):
        mock_engine, mock_conn = _mock_engine_begin()

        with (
            patch("src.seeding.service.reseed.engine", mock_engine),
            patch("src.seeding.service.reseed.DROP_BACKUP_AFTER_SWAP", True),
        ):
            await swap_tables("main", "staging", "backup")

        assert mock_conn.execute.call_count == 6
        sqls = [str(c[0][0].text) for c in mock_conn.execute.call_args_list]
        assert "LOCK" in sqls[0]
        assert "RENAME" in sqls[1]
        assert "RENAME CONSTRAINT" in sqls[2]
        assert "RENAME" in sqls[3]
        assert "DROP" in sqls[4]
        assert "RENAME CONSTRAINT" in sqls[5]

    async def test_skips_drop_when_flag_false(self):
        mock_engine, mock_conn = _mock_engine_begin()

        with (
            patch("src.seeding.service.reseed.engine", mock_engine),
            patch("src.seeding.service.reseed.DROP_BACKUP_AFTER_SWAP", False),
        ):
            await swap_tables("main", "staging", "backup")

        assert mock_conn.execute.call_count == 5


class TestRebuildIndexes:
    async def test_creates_five_indexes_and_analyze(self):
        mock_engine, mock_conn = _mock_engine_connect()

        with (
            patch("src.seeding.service.reseed.engine", mock_engine),
            patch("src.seeding.service.reseed.DROP_BACKUP_AFTER_SWAP", True),
        ):
            await rebuild_indexes("documents")

        assert mock_conn.execute.call_count == 6
        sqls = [str(call.args[0].text) for call in mock_conn.execute.call_args_list]
        assert any("USING bm25" in sql for sql in sqls)
        assert any("metadata_json jsonb_path_ops" in sql for sql in sqls)

    async def test_skips_when_drop_backup_false(self):
        mock_engine, mock_conn = _mock_engine_connect()

        with (
            patch("src.seeding.service.reseed.engine", mock_engine),
            patch("src.seeding.service.reseed.DROP_BACKUP_AFTER_SWAP", False),
        ):
            await rebuild_indexes("documents")

        assert mock_conn.execute.call_count == 0


class TestReseed:
    async def test_calls_all_steps_in_order(self):
        with (
            patch(
                "src.seeding.service.reseed.ensure_extensions", new_callable=AsyncMock
            ) as m_ext,
            patch(
                "src.seeding.service.reseed.recreate_staging", new_callable=AsyncMock
            ) as m_recreate,
            patch("src.seeding.service.reseed.seed", new_callable=AsyncMock) as m_seed,
            patch(
                "src.seeding.service.reseed.swap_tables", new_callable=AsyncMock
            ) as m_swap,
            patch(
                "src.seeding.service.reseed.rebuild_indexes", new_callable=AsyncMock
            ) as m_rebuild,
        ):
            await reseed()

        m_ext.assert_awaited_once()
        m_recreate.assert_awaited_once_with(MAIN_TABLE, STAGING_TABLE)
        # on_chunk_done and start_chunk are also passed; check only the required kwargs
        m_seed.assert_awaited_once()
        call_kwargs = m_seed.await_args.kwargs
        assert call_kwargs["target_table"] == STAGING_TABLE
        assert call_kwargs["start_chunk"] == 0
        m_swap.assert_awaited_once_with(MAIN_TABLE, STAGING_TABLE, BACKUP_TABLE)
        m_rebuild.assert_awaited_once_with(MAIN_TABLE)

    async def test_calls_on_step_callback(self):
        steps: list[str] = []

        def callback(msg):
            steps.append(msg)

        with (
            patch(
                "src.seeding.service.reseed.ensure_extensions", new_callable=AsyncMock
            ),
            patch(
                "src.seeding.service.reseed.recreate_staging", new_callable=AsyncMock
            ),
            patch("src.seeding.service.reseed.seed", new_callable=AsyncMock),
            patch("src.seeding.service.reseed.swap_tables", new_callable=AsyncMock),
            patch("src.seeding.service.reseed.rebuild_indexes", new_callable=AsyncMock),
        ):
            await reseed(on_step=callback)

        assert len(steps) == 5
        assert "1/5" in steps[0]
        assert "2/5" in steps[1]
        assert "3/5" in steps[2]
        assert "4/5" in steps[3]
        assert "5/5" in steps[4]

    async def test_skips_recreate_staging_when_resuming(self):
        """When start_chunk > 0 and staging has enough rows, recreate_staging must not be called."""
        with (
            patch(
                "src.seeding.service.reseed.ensure_extensions", new_callable=AsyncMock
            ),
            patch(
                "src.seeding.service.reseed.recreate_staging", new_callable=AsyncMock
            ) as m_recreate,
            patch("src.seeding.service.reseed.seed", new_callable=AsyncMock) as m_seed,
            patch("src.seeding.service.reseed.swap_tables", new_callable=AsyncMock),
            patch("src.seeding.service.reseed.rebuild_indexes", new_callable=AsyncMock),
            patch(
                "src.seeding.service.reseed._count_rows",
                new_callable=AsyncMock,
                return_value=10_000,
            ),
        ):
            await reseed(start_chunk=5)

        m_recreate.assert_not_awaited()
        call_kwargs = m_seed.await_args.kwargs
        assert call_kwargs["start_chunk"] == 5

    async def test_falls_back_to_fresh_start_when_staging_incomplete(self):
        """When resuming, if staging table row count is too low, fall back to fresh start."""
        with (
            patch(
                "src.seeding.service.reseed.ensure_extensions", new_callable=AsyncMock
            ),
            patch(
                "src.seeding.service.reseed.recreate_staging", new_callable=AsyncMock
            ) as m_recreate,
            patch("src.seeding.service.reseed.seed", new_callable=AsyncMock) as m_seed,
            patch("src.seeding.service.reseed.swap_tables", new_callable=AsyncMock),
            patch("src.seeding.service.reseed.rebuild_indexes", new_callable=AsyncMock),
            patch(
                "src.seeding.service.reseed._count_rows",
                new_callable=AsyncMock,
                return_value=100,
            ),
        ):
            await reseed(start_chunk=50)

        m_recreate.assert_awaited_once()
        assert m_seed.await_args.kwargs["start_chunk"] == 0

    async def test_falls_back_when_staging_at_one_below_threshold(self):
        """Boundary: exactly one row below threshold triggers fallback."""
        threshold = (50 - 1) * 2000  # 98_000
        with (
            patch(
                "src.seeding.service.reseed.ensure_extensions", new_callable=AsyncMock
            ),
            patch(
                "src.seeding.service.reseed.recreate_staging", new_callable=AsyncMock
            ) as m_recreate,
            patch("src.seeding.service.reseed.seed", new_callable=AsyncMock) as m_seed,
            patch("src.seeding.service.reseed.swap_tables", new_callable=AsyncMock),
            patch("src.seeding.service.reseed.rebuild_indexes", new_callable=AsyncMock),
            patch(
                "src.seeding.service.reseed._count_rows",
                new_callable=AsyncMock,
                return_value=threshold - 1,
            ),
        ):
            await reseed(start_chunk=50)

        m_recreate.assert_awaited_once()
        assert m_seed.await_args.kwargs["start_chunk"] == 0

    async def test_continues_resume_at_exact_threshold(self):
        """Boundary: exactly at threshold allows resume."""
        threshold = (50 - 1) * 2000  # 98_000
        with (
            patch(
                "src.seeding.service.reseed.ensure_extensions", new_callable=AsyncMock
            ),
            patch(
                "src.seeding.service.reseed.recreate_staging", new_callable=AsyncMock
            ) as m_recreate,
            patch("src.seeding.service.reseed.seed", new_callable=AsyncMock) as m_seed,
            patch("src.seeding.service.reseed.swap_tables", new_callable=AsyncMock),
            patch("src.seeding.service.reseed.rebuild_indexes", new_callable=AsyncMock),
            patch(
                "src.seeding.service.reseed._count_rows",
                new_callable=AsyncMock,
                return_value=threshold,
            ),
        ):
            await reseed(start_chunk=50)

        m_recreate.assert_not_awaited()
        assert m_seed.await_args.kwargs["start_chunk"] == 50

    async def test_continues_resume_when_staging_has_enough_rows(self):
        """When resuming and staging has sufficient rows, continue from start_chunk."""
        with (
            patch(
                "src.seeding.service.reseed.ensure_extensions", new_callable=AsyncMock
            ),
            patch(
                "src.seeding.service.reseed.recreate_staging", new_callable=AsyncMock
            ) as m_recreate,
            patch("src.seeding.service.reseed.seed", new_callable=AsyncMock) as m_seed,
            patch("src.seeding.service.reseed.swap_tables", new_callable=AsyncMock),
            patch("src.seeding.service.reseed.rebuild_indexes", new_callable=AsyncMock),
            patch(
                "src.seeding.service.reseed._count_rows",
                new_callable=AsyncMock,
                return_value=100_000,
            ),
        ):
            await reseed(start_chunk=50)

        m_recreate.assert_not_awaited()
        assert m_seed.await_args.kwargs["start_chunk"] == 50

    async def test_passes_on_chunk_done_to_seed(self):
        """on_chunk_done callback is forwarded to seed()."""
        chunk_callback = MagicMock()

        with (
            patch(
                "src.seeding.service.reseed.ensure_extensions", new_callable=AsyncMock
            ),
            patch(
                "src.seeding.service.reseed.recreate_staging", new_callable=AsyncMock
            ),
            patch("src.seeding.service.reseed.seed", new_callable=AsyncMock) as m_seed,
            patch("src.seeding.service.reseed.swap_tables", new_callable=AsyncMock),
            patch("src.seeding.service.reseed.rebuild_indexes", new_callable=AsyncMock),
        ):
            await reseed(on_chunk_done=chunk_callback)

        assert m_seed.await_args.kwargs["on_chunk_done"] is chunk_callback
