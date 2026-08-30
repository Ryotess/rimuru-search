"""Chunk processing logic for the seeding pipeline.

Moved from scripts/hybrid_db/seed.py to allow reuse and testability.
"""

import gc
from typing import Any, cast

from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import app_settings
from src.database import SessionLocal
from src.logging_config import logger
from src.models import Document
from src.seeding.constants import DB_BATCH_SIZE, EMBED_BATCH_SIZE
from src.seeding.service.embedding import embed_in_chunks


def _resolve_target_table(table_name: str) -> tuple[Table, bool]:
    """Return target Table and whether it is the default Document table."""
    document_table = cast(Table, Document.__table__)
    if table_name == Document.__tablename__:
        return document_table, True
    metadata = MetaData()
    return document_table.to_metadata(metadata, name=table_name), False


async def process_chunk(
    rows: list[dict[str, Any]],
    target_table_name: str,
    client: AsyncHTTPHandler | None = None,
) -> int:
    """Embed and insert one chunk, then free its memory. Returns inserted count."""
    if not rows:
        return 0

    contents = []
    ids = []
    metadata_items = []
    collections = []
    for row in rows:
        content = row.get("content")
        if content is None or str(content).strip() == "":
            logger.bind(
                document_id=str(row.get("id") or ""),
                collection=str(row.get("collection") or ""),
            ).warning("Skipping row with missing content")
            continue
        document_id = row.get("id")
        if document_id is None or str(document_id).strip() == "":
            logger.bind(collection=str(row.get("collection") or "")).warning(
                "Skipping row with missing ID"
            )
            continue
        contents.append(str(content))
        ids.append(str(document_id))
        metadata_items.append(row.get("metadata") or {})
        collection = str(
            row.get("collection") or app_settings.document_default_collection
        ).strip()
        if not collection:
            logger.bind(document_id=str(document_id)).warning(
                "Skipping row with empty collection"
            )
            contents.pop()
            ids.pop()
            metadata_items.pop()
            continue
        collections.append(collection)

    logger.info(f"Embedding {len(contents)} rows...")
    embs = await embed_in_chunks(contents, EMBED_BATCH_SIZE, client=client)
    if len(embs) != len(contents):
        raise ValueError("Embeddings count mismatch with rows in chunk.")

    embs_list = cast(list[list[float]], embs.tolist())
    del embs

    logger.info("Inserting into DB...")
    target_table, is_default = _resolve_target_table(target_table_name)

    async def _flush(session, buf):
        if is_default:
            insert_stmt = pg_insert(target_table).values(buf)
            upsert_stmt = insert_stmt.on_conflict_do_update(
                index_elements=[target_table.c.collection, target_table.c.id],
                set_={
                    "content": insert_stmt.excluded.content,
                    "metadata_json": insert_stmt.excluded.metadata_json,
                    "embedding": insert_stmt.excluded.embedding,
                },
            )
            await session.execute(upsert_stmt)
        else:
            await session.execute(target_table.insert(), buf)
        await session.commit()

    async with SessionLocal() as session:
        buf = []
        total = len(contents)
        for pos, content in enumerate(contents):
            payload = {
                "collection": collections[pos],
                "id": ids[pos],
                "content": content,
                "metadata_json": metadata_items[pos],
                "embedding": embs_list[pos],
            }
            buf.append(payload)

            if len(buf) >= DB_BATCH_SIZE:
                await _flush(session, buf)
                logger.info(f"Committed {min(pos + 1, total)}/{total} in this chunk")
                buf.clear()

        if buf:
            await _flush(session, buf)
            logger.info(f"Committed final {len(buf)} rows in this chunk")

    del rows, contents, ids, metadata_items, collections, embs_list, buf
    gc.collect()
    return total
