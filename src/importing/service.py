from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.cache import get_redis, invalidate_search_cache
from src.importing.reader import (
    ImportDataError,
    ImportFormat,
    ImportMapping,
    detect_format,
    iter_raw_records,
    map_record,
)
from src.logging_config import logger
from src.models import Document
from src.seeding.constants import ROWS_PER_CHUNK
from src.seeding.service.chunk_processor import process_chunk
from src.seeding.service.embedding import short_keepalive_client
from src.seeding.service.reseed import (
    BACKUP_TABLE,
    MAIN_TABLE,
    STAGING_TABLE,
    ensure_extensions,
    rebuild_indexes,
    recreate_staging,
    swap_tables,
)
from src.seeding.service.retry import retry_with_backoff

ImportMode = Literal["upsert", "replace"]


@dataclass(frozen=True)
class ImportSummary:
    path: str
    mode: ImportMode
    rows: int
    chunks: int
    elapsed_seconds: float
    dry_run: bool = False


async def import_file(
    path: Path,
    *,
    mapping: ImportMapping,
    mode: ImportMode = "upsert",
    input_format: ImportFormat | None = None,
    encoding: str = "utf-8",
    csv_delimiter: str = ",",
    chunk_size: int = ROWS_PER_CHUNK,
    dry_run: bool = False,
) -> ImportSummary:
    """Validate, embed, and import JSON, JSONL, or CSV documents."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    resolved_format = detect_format(path, input_format)
    start = time.monotonic()
    total_rows = 0
    total_chunks = 0
    seen_ids: set[tuple[str, str]] = set()
    target_table = Document.__tablename__

    if mode == "replace" and not dry_run:
        await ensure_extensions()
        await recreate_staging(MAIN_TABLE, STAGING_TABLE)
        target_table = STAGING_TABLE

    async def _consume(client=None) -> None:
        nonlocal total_chunks, total_rows
        chunk: list[dict[str, Any]] = []
        for record_number, raw_record in iter_raw_records(
            path,
            resolved_format,
            encoding=encoding,
            csv_delimiter=csv_delimiter,
        ):
            document = map_record(raw_record, mapping, record_number)
            document_key = (document["collection"], document["id"])
            if document_key in seen_ids:
                raise ImportDataError(
                    f"Duplicate document ID '{document['id']}' in collection "
                    f"'{document['collection']}' at record {record_number}"
                )
            seen_ids.add(document_key)
            chunk.append(document)

            if len(chunk) >= chunk_size:
                total_rows += await _process(chunk, target_table, client, dry_run)
                total_chunks += 1
                chunk = []

        if chunk:
            total_rows += await _process(chunk, target_table, client, dry_run)
            total_chunks += 1

    if dry_run:
        await _consume()
    else:
        async with short_keepalive_client() as client:
            await _consume(client)

    if total_rows == 0:
        raise ImportDataError("Input contains no documents; nothing was changed")

    if not dry_run:
        if mode == "replace":
            await swap_tables(MAIN_TABLE, STAGING_TABLE, BACKUP_TABLE)
            await invalidate_search_cache(get_redis())
            await rebuild_indexes(MAIN_TABLE)
        else:
            await invalidate_search_cache(get_redis())

    elapsed = time.monotonic() - start
    logger.bind(
        path=str(path),
        mode=mode,
        rows=total_rows,
        chunks=total_chunks,
        dry_run=dry_run,
        elapsed_seconds=round(elapsed, 2),
    ).info("File import completed")
    return ImportSummary(
        path=str(path),
        mode=mode,
        rows=total_rows,
        chunks=total_chunks,
        dry_run=dry_run,
        elapsed_seconds=round(elapsed, 3),
    )


async def _process(
    rows: list[dict[str, Any]], target_table: str, client, dry_run: bool
) -> int:
    if dry_run:
        return len(rows)
    return await retry_with_backoff(
        lambda: process_chunk(rows, target_table, client=client),
        max_retries=2,
        base_delay=5.0,
    )
