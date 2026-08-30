#!/usr/bin/env python3
import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import global_settings
from src.models import Document


def _as_async_url(url: str):
    db_url = make_url(url)
    if (
        db_url.drivername.startswith("postgresql")
        and "+psycopg" not in db_url.drivername
    ):
        db_url = db_url.set(drivername="postgresql+psycopg")
    return db_url


def _open_output(path: str):
    if path == "-":
        return sys.stdout
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path.open("w", encoding="utf-8")


async def dump_documents(
    db_url: str,
    output_path: str,
    output_format: str,
    chunk_size: int,
    limit: int | None,
):
    engine = create_async_engine(_as_async_url(db_url), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    query = select(
        Document.collection,
        Document.id,
        Document.content,
        Document.metadata_json,
        Document.embedding,
    ).order_by(Document.collection, Document.id)
    if limit:
        query = query.limit(limit)
    query = query.execution_options(yield_per=chunk_size)

    async with session_factory() as session:
        result = await session.stream(query)
        with _open_output(output_path) as handle:
            if output_format == "csv":
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "collection",
                        "id",
                        "content",
                        "metadata",
                        "embedding",
                    ],
                )
                writer.writeheader()
                async for row in result:
                    payload = {
                        "collection": row.collection,
                        "id": str(row.id),
                        "content": row.content,
                        "metadata": json.dumps(row.metadata_json, ensure_ascii=True),
                        "embedding": json.dumps(row.embedding, ensure_ascii=True),
                    }
                    writer.writerow(payload)
            else:
                async for row in result:
                    embedding = row.embedding
                    if hasattr(embedding, "tolist"):
                        embedding = embedding.tolist()
                    payload = {
                        "collection": row.collection,
                        "id": str(row.id),
                        "content": row.content,
                        "metadata": row.metadata_json,
                        "embedding": embedding,
                    }
                    handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    await engine.dispose()


def _parse_args():
    parser = argparse.ArgumentParser(description="Dump documents to JSONL or CSV.")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Database URL. Defaults to GLOBAL_DATABASE_URL from config.",
    )
    parser.add_argument(
        "--out",
        default="scripts/documents.jsonl",
        help="Output path, or '-' for stdout.",
    )
    parser.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        default="jsonl",
        help="Output format.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=2000,
        help="Rows per server-side fetch.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of rows to export.",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    db_url = args.db_url or global_settings.database_url
    if not db_url:
        raise SystemExit("Missing --db-url or GLOBAL_DATABASE_URL.")
    asyncio.run(
        dump_documents(
            db_url=db_url,
            output_path=args.out,
            output_format=args.format,
            chunk_size=args.chunk_size,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
