"""Top-level seeding orchestrator.

Moved from scripts/hybrid_db/seed.py to allow reuse by the seeding router
and background task API.
"""

import os
import time
from collections.abc import Awaitable, Callable
from functools import partial
from inspect import isawaitable

from src.cache import get_redis, invalidate_search_cache
from src.logging_config import logger
from src.models import Document
from src.seeding.constants import ROWS_PER_CHUNK
from src.seeding.service.chunk_processor import process_chunk
from src.seeding.service.embedding import short_keepalive_client
from src.seeding.service.retry import retry_with_backoff
from src.source_api.service import iter_documents

DEFAULT_TARGET_TABLE = os.getenv("TARGET_TABLE", Document.__tablename__)


async def seed(
    target_table: str | None = None,
    on_chunk_done: Callable[[int, int], Awaitable[None] | None] | None = None,
    start_chunk: int = 0,
) -> int:
    """Run the full seeding pipeline: iterate source rows, embed, and insert.

    Args:
        target_table: Override the destination table name. Defaults to
            ``Document.__tablename__`` (or the ``TARGET_TABLE`` env-var).
        on_chunk_done: Optional callback invoked after each chunk with
            ``(chunk_index, rows_inserted)``.
        start_chunk: Resume from this chunk index (0 = fresh start).
            Chunks 1..start_chunk are skipped (already committed).

    Returns:
        Total number of rows inserted.
    """
    start = time.time()
    target_table_name = target_table or DEFAULT_TARGET_TABLE
    logger.info("Starting vector DB seeding process...")
    logger.info(f"Target table: {target_table_name}")

    total_rows = 0
    chunk_idx = start_chunk

    async with short_keepalive_client() as client:
        async for rows in iter_documents(
            page_size=ROWS_PER_CHUNK, start_page=start_chunk + 1
        ):
            chunk_idx += 1
            logger.info(f"Processing chunk {chunk_idx} with {len(rows)} rows...")
            inserted = await retry_with_backoff(
                partial(process_chunk, rows, target_table_name, client=client),
                max_retries=2,
                base_delay=5.0,
            )
            total_rows += inserted
            if on_chunk_done is not None:
                callback_result = on_chunk_done(chunk_idx, inserted)
                if isawaitable(callback_result):
                    await callback_result

    elapsed = time.time() - start
    logger.success(
        f"Seeding complete. Rows processed: {total_rows}. Time: {elapsed:.2f}s"
    )
    if target_table_name == DEFAULT_TARGET_TABLE:
        await invalidate_search_cache(get_redis())
    return total_rows
