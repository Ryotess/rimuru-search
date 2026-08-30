#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from src.config import app_settings
from src.importing import ImportDataError, ImportMapping, import_file
from src.importing.reader import parse_field_list
from src.logging_config import shutdown_logging


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import JSON, JSONL, or CSV into the hybrid-search database. "
            "Defaults come from .env and every option can be overridden here."
        )
    )
    parser.add_argument("path", type=Path, help="Input JSON, JSONL, or CSV file")
    parser.add_argument("--format", choices=("json", "jsonl", "csv"), default=None)
    parser.add_argument(
        "--collection",
        default=app_settings.document_default_collection,
        help="Collection used when the input has no configured collection field.",
    )
    parser.add_argument(
        "--collection-field",
        default=app_settings.import_collection_field,
        help="Optional source field containing each record's collection.",
    )
    parser.add_argument("--id-field", default=app_settings.import_id_field)
    parser.add_argument(
        "--content-fields",
        default=app_settings.import_content_fields,
        help="Comma-separated fields joined to form searchable content; dot paths work.",
    )
    parser.add_argument(
        "--metadata-fields",
        default=app_settings.import_metadata_fields,
        help="Comma-separated fields to retain; empty keeps every unused top-level field.",
    )
    parser.add_argument(
        "--generate-ids",
        action=argparse.BooleanOptionalAction,
        default=app_settings.import_generate_ids,
        help="Generate stable record-based IDs when the configured ID field is absent.",
    )
    parser.add_argument(
        "--mode",
        choices=("upsert", "replace"),
        default=app_settings.import_mode,
        help=(
            "upsert updates matching IDs; replace atomically swaps a complete "
            "service-wide snapshot, removing collections absent from the input."
        ),
    )
    parser.add_argument("--encoding", default=app_settings.import_file_encoding)
    parser.add_argument("--delimiter", default=app_settings.import_csv_delimiter)
    parser.add_argument(
        "--chunk-size", type=int, default=app_settings.seed_rows_per_chunk
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate mapping and IDs without embedding or writing to the database.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    mapping = ImportMapping(
        collection=args.collection,
        collection_field=args.collection_field or None,
        id_field=args.id_field,
        content_fields=parse_field_list(args.content_fields),
        metadata_fields=parse_field_list(args.metadata_fields),
        generate_ids=args.generate_ids,
    )
    summary = await import_file(
        args.path,
        mapping=mapping,
        mode=args.mode,
        input_format=args.format,
        encoding=args.encoding,
        csv_delimiter=args.delimiter,
        chunk_size=args.chunk_size,
        dry_run=args.dry_run,
    )
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(_run(args))
    except ImportDataError as exc:
        raise SystemExit(f"Import failed: {exc}") from exc
    finally:
        shutdown_logging()


if __name__ == "__main__":
    main()
