"""
Reseed flow that avoids touching the live table until data is ready:
1) Ensure extensions/functions exist.
2) Create a staging table based on the current main table schema (no indexes).
3) Run the embedding seed into staging.
4) Atomically swap staging -> main (main -> backup), then drop the backup.
5) Rebuild indexes on the new main table.
"""

import os
import re
from collections.abc import Awaitable, Callable, Iterable

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from src.cache import get_redis, invalidate_search_cache
from src.database import engine
from src.logging_config import logger
from src.models import Document
from src.seeding.constants import ROWS_PER_CHUNK
from src.seeding.service.seeder import seed

NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

MAIN_TABLE = os.getenv("MAIN_TABLE", Document.__tablename__)
STAGING_TABLE = os.getenv("STAGING_TABLE", f"{MAIN_TABLE}_staging")
BACKUP_TABLE = os.getenv("BACKUP_TABLE", f"{MAIN_TABLE}_backup")
DROP_BACKUP_AFTER_SWAP = os.getenv("DROP_BACKUP_AFTER_SWAP", "true").lower() in {
    "true",
    "1",
    "yes",
}


def _validate_identifiers(names: Iterable[str]) -> None:
    for name in names:
        if not NAME_RE.fullmatch(name):
            raise ValueError(f"Invalid table/index identifier: {name}")


async def ensure_extensions() -> None:
    """Ensure required extensions/functions exist."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.execute(
            text("CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;")
        )
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_textsearch;"))
        await conn.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION immutable_unaccent(text)
                RETURNS text
                LANGUAGE sql
                IMMUTABLE
                PARALLEL SAFE
                AS $$
                    SELECT public.unaccent($1);
                $$;
                """
            )
        )
    logger.info("Ensured extensions/functions are present.")


async def recreate_staging(main_table: str, staging_table: str) -> None:
    """
    Build a fresh staging table with the same columns/generators as the main table.
    Indexes are intentionally omitted to avoid name conflicts; they are rebuilt after swap.
    """
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{staging_table}" CASCADE'))
        await conn.execute(
            text(
                f'CREATE TABLE "{staging_table}"'
                f' (LIKE "{main_table}" INCLUDING DEFAULTS INCLUDING CONSTRAINTS'
                f" INCLUDING GENERATED INCLUDING IDENTITY INCLUDING STORAGE INCLUDING COMMENTS)"
            )
        )
        await conn.execute(
            text(f'ALTER TABLE "{staging_table}" ADD PRIMARY KEY (collection, id)')
        )
    logger.info(
        f"Recreated staging table {staging_table} from {main_table} "
        "with collection-scoped identity."
    )


async def swap_tables(main_table: str, staging_table: str, backup_table: str) -> None:
    """Swap staging into main, optionally dropping the backup to free index names."""
    main_pkey = f"{main_table}_pkey"
    staging_pkey = f"{staging_table}_pkey"
    backup_pkey = f"{backup_table}_pkey"
    _validate_identifiers([main_pkey, staging_pkey, backup_pkey])

    async with engine.begin() as conn:
        await conn.execute(text(f'LOCK TABLE "{main_table}" IN ACCESS EXCLUSIVE MODE'))
        await conn.execute(
            text(f'ALTER TABLE "{main_table}" RENAME TO "{backup_table}"')
        )
        await conn.execute(
            text(
                f'ALTER TABLE "{backup_table}" '
                f'RENAME CONSTRAINT "{main_pkey}" TO "{backup_pkey}"'
            )
        )
        await conn.execute(
            text(f'ALTER TABLE "{staging_table}" RENAME TO "{main_table}"')
        )
        if DROP_BACKUP_AFTER_SWAP:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{backup_table}" CASCADE'))
            logger.info(f"Dropped backup table {backup_table} after swap.")
        else:
            logger.info(f"Kept backup table as {backup_table}.")
        await conn.execute(
            text(
                f'ALTER TABLE "{main_table}" '
                f'RENAME CONSTRAINT "{staging_pkey}" TO "{main_pkey}"'
            )
        )
    logger.info("Swapped staging into main.")


async def rebuild_indexes(table_name: str) -> None:
    """Recreate indexes on the new main table. Runs concurrently to avoid long locks."""
    if not DROP_BACKUP_AFTER_SWAP:
        logger.warning(
            "Skipped index rebuild because backup table was kept; "
            "drop the backup and rerun if you want fresh indexes on the new main table."
        )
        return

    gin_index = f"{table_name}_content_tsv_gin_idx"
    hnsw_index = f"{table_name}_embedding_hnsw_idx"
    trgm_index = f"{table_name}_content_trgm_idx"
    bm25_index = f"{table_name}_content_bm25_idx"
    metadata_index = f"{table_name}_metadata_json_gin_idx"

    stmts = [
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {gin_index} ON "{table_name}" USING gin (content_tsv);',
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {trgm_index} ON "{table_name}" USING gin (immutable_unaccent(content) gin_trgm_ops);',
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {bm25_index} ON \"{table_name}\" USING bm25 ((immutable_unaccent(content))) WITH (text_config = 'simple');",
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {metadata_index} ON "{table_name}" USING gin (metadata_json jsonb_path_ops);',
        f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {hnsw_index} ON "{table_name}" USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200);',
        f'ANALYZE "{table_name}";',
    ]

    for stmt in stmts:
        async with engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit_conn.execute(text(stmt))
    logger.info("Rebuilt indexes on new main table.")


async def _count_rows(table: str) -> int:
    """Count rows in a table. Returns 0 if the table does not exist."""
    async with engine.begin() as conn:
        try:
            result = await conn.execute(
                text(f'SELECT COUNT(*) FROM "{table}"')  # noqa: S608  # Identifier is validated before reseeding starts.
            )
            return result.scalar_one()
        except ProgrammingError:
            return 0


async def reseed(
    on_step: Callable[[str], None] | None = None,
    on_chunk_done: Callable[[int, int], Awaitable[None] | None] | None = None,
    start_chunk: int = 0,
) -> None:
    """Orchestrate the full reseed flow with optional step callback.

    Args:
        on_step: Optional callback invoked at each step boundary.
        start_chunk: Resume from this chunk (0 = fresh start).
            When > 0, recreate_staging is skipped — staging table already
            contains chunks 1..start_chunk from the interrupted run.
    """
    _validate_identifiers([MAIN_TABLE, STAGING_TABLE, BACKUP_TABLE])

    def _notify(msg: str) -> None:
        if on_step:
            on_step(msg)

    logger.info(
        f"Reseed start | main={MAIN_TABLE}, staging={STAGING_TABLE}, "
        f"backup={BACKUP_TABLE}, drop_backup={DROP_BACKUP_AFTER_SWAP}, "
        f"start_chunk={start_chunk}"
    )

    _notify("Step 1/5: Ensuring extensions")
    await ensure_extensions()

    if start_chunk == 0:
        _notify("Step 2/5: Recreating staging table")
        await recreate_staging(MAIN_TABLE, STAGING_TABLE)
    else:
        expected_min = (start_chunk - 1) * ROWS_PER_CHUNK
        actual = await _count_rows(STAGING_TABLE)
        if actual < expected_min:
            logger.warning(
                "Staging has {} rows, expected >= {} (chunks_completed={}). "
                "Falling back to fresh start.",
                actual,
                expected_min,
                start_chunk,
            )
            start_chunk = 0
            _notify("Step 2/5: Recreating staging table (fallback)")
            await recreate_staging(MAIN_TABLE, STAGING_TABLE)
        else:
            logger.info(
                "Staging verified: {} rows, resuming from chunk {}",
                actual,
                start_chunk + 1,
            )
            _notify(f"Step 2/5: Resuming staging table from chunk {start_chunk + 1}")

    _notify("Step 3/5: Seeding staging table")
    await seed(
        target_table=STAGING_TABLE,
        on_chunk_done=on_chunk_done,
        start_chunk=start_chunk,
    )

    _notify("Step 4/5: Swapping tables")
    await swap_tables(MAIN_TABLE, STAGING_TABLE, BACKUP_TABLE)
    await invalidate_search_cache(get_redis())

    _notify("Step 5/5: Rebuilding indexes")
    await rebuild_indexes(MAIN_TABLE)

    logger.success("Reseed completed successfully.")
