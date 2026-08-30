#!/usr/bin/env python3
import argparse
import asyncio
import csv
import json
from pathlib import Path

from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import app_settings, global_settings
from src.models import Document


def _as_async_url(url: str):
    db_url = make_url(url)
    if (
        db_url.drivername.startswith("postgresql")
        and "+psycopg" not in db_url.drivername
    ):
        db_url = db_url.set(drivername="postgresql+psycopg")
    return db_url


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _iter_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        yield from reader


def _normalize_row(row: dict):
    embedding = row.get("embedding")
    if isinstance(embedding, str):
        embedding = json.loads(embedding)
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return {
        "collection": row.get("collection") or app_settings.document_default_collection,
        "id": row.get("id"),
        "content": row.get("content"),
        "metadata_json": metadata,
        "embedding": embedding,
    }


async def load_documents(
    db_url: str,
    input_path: str,
    input_format: str,
    batch_size: int,
    upsert: bool,
):
    engine = create_async_engine(_as_async_url(db_url), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    path = Path(input_path)
    row_iter = _iter_jsonl(path) if input_format == "jsonl" else _iter_csv(path)

    async with session_factory() as session:
        buf: list[dict] = []
        for row in row_iter:
            buf.append(_normalize_row(row))
            if len(buf) >= batch_size:
                await _flush_batch(session, buf, upsert)
                buf.clear()
        if buf:
            await _flush_batch(session, buf, upsert)

    await engine.dispose()


async def _flush_batch(session, rows: list[dict], upsert: bool):
    if upsert:
        stmt = pg_insert(Document).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Document.collection, Document.id],
            set_={
                "content": stmt.excluded.content,
                "metadata_json": stmt.excluded.metadata_json,
                "embedding": stmt.excluded.embedding,
            },
        )
    else:
        stmt = insert(Document).values(rows)
    await session.execute(stmt)
    await session.commit()


def _parse_args():
    parser = argparse.ArgumentParser(description="Load documents from JSONL or CSV.")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL. Defaults to GLOBAL_DATABASE_URL from config.",
    )
    parser.add_argument(
        "--in",
        dest="input_path",
        default="scripts/documents.jsonl",
        help="Input path.",
    )
    parser.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        default="jsonl",
        help="Input format.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Rows per insert batch.",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="Upsert on id conflicts instead of failing.",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    input_path = Path(args.input_path)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")
    db_url = args.db_url or global_settings.database_url
    if not db_url:
        raise SystemExit("Missing --db-url or GLOBAL_DATABASE_URL.")
    asyncio.run(
        load_documents(
            db_url=db_url,
            input_path=str(input_path),
            input_format=args.format,
            batch_size=args.batch_size,
            upsert=args.upsert,
        )
    )


if __name__ == "__main__":
    main()
