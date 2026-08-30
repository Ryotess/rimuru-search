from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ImportFormat = Literal["json", "jsonl", "csv"]


class ImportDataError(ValueError):
    """Raised when an input record cannot be mapped to the document contract."""


@dataclass(frozen=True)
class ImportMapping:
    collection: str = "default"
    collection_field: str | None = "collection"
    id_field: str = "id"
    content_fields: tuple[str, ...] = ("content",)
    metadata_fields: tuple[str, ...] = ()
    generate_ids: bool = False
    content_separator: str = "\n\n"


def parse_field_list(value: str) -> tuple[str, ...]:
    """Parse a comma-separated dotenv or CLI value into field names."""
    return tuple(field.strip() for field in value.split(",") if field.strip())


def detect_format(path: Path, explicit_format: str | None = None) -> ImportFormat:
    if explicit_format:
        if explicit_format not in {"json", "jsonl", "csv"}:
            raise ImportDataError(f"Unsupported input format: {explicit_format}")
        return explicit_format  # type: ignore[return-value]

    suffix = path.suffix.lower()
    formats: dict[str, ImportFormat] = {
        ".json": "json",
        ".jsonl": "jsonl",
        ".ndjson": "jsonl",
        ".csv": "csv",
    }
    try:
        return formats[suffix]
    except KeyError as exc:
        raise ImportDataError(
            f"Cannot detect format from '{path.name}'. Use --format json, jsonl, or csv."
        ) from exc


def iter_raw_records(
    path: Path,
    input_format: ImportFormat,
    *,
    encoding: str = "utf-8",
    csv_delimiter: str = ",",
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield 1-indexed records without loading JSONL or CSV files into memory."""
    if not path.is_file():
        raise ImportDataError(f"Input file not found: {path}")

    if input_format == "jsonl":
        with path.open("r", encoding=encoding) as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ImportDataError(
                        f"Invalid JSON on line {line_number}: {exc.msg}"
                    ) from exc
                yield line_number, _require_object(value, f"line {line_number}")
        return

    if input_format == "csv":
        with path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=csv_delimiter)
            if not reader.fieldnames:
                raise ImportDataError("CSV file must contain a header row")
            for line_number, row in enumerate(reader, start=2):
                yield line_number, dict(row)
        return

    try:
        value = json.loads(path.read_text(encoding=encoding))
    except json.JSONDecodeError as exc:
        raise ImportDataError(f"Invalid JSON: {exc.msg}") from exc

    if isinstance(value, list):
        records = value
    elif isinstance(value, Mapping) and isinstance(value.get("documents"), list):
        records = value["documents"]
    elif isinstance(value, Mapping) and isinstance(value.get("data"), list):
        records = value["data"]
    else:
        records = [value]

    for index, record in enumerate(records, start=1):
        yield index, _require_object(record, f"record {index}")


def map_record(
    record: dict[str, Any], mapping: ImportMapping, record_number: int
) -> dict[str, Any]:
    """Map an arbitrary object into ``id``, ``content``, and ``metadata``."""
    if not mapping.content_fields:
        raise ImportDataError("At least one content field is required")

    content_parts = [
        _as_text(_get_field(record, field)) for field in mapping.content_fields
    ]
    content = mapping.content_separator.join(part for part in content_parts if part)
    if not content.strip():
        fields = ", ".join(mapping.content_fields)
        raise ImportDataError(
            f"Record {record_number} has no content in configured field(s): {fields}"
        )

    collection = mapping.collection
    if mapping.collection_field:
        record_collection = _as_text(_get_field(record, mapping.collection_field))
        if record_collection:
            collection = record_collection
    if not collection.strip():
        raise ImportDataError(
            f"Record {record_number} has no collection in "
            f"'{mapping.collection_field or 'configured default'}'"
        )

    raw_id = _get_field(record, mapping.id_field)
    document_id = _as_text(raw_id).strip()
    if not document_id:
        if not mapping.generate_ids:
            raise ImportDataError(
                f"Record {record_number} has no ID in '{mapping.id_field}'. "
                "Set IMPORT_GENERATE_IDS=true or pass --generate-ids to create stable IDs."
            )
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        document_id = f"doc-{hashlib.sha256(canonical.encode()).hexdigest()[:20]}"

    metadata = _extract_metadata(record, mapping)
    return {
        "collection": collection.strip(),
        "id": document_id,
        "content": content,
        "metadata": metadata,
    }


def _extract_metadata(record: dict[str, Any], mapping: ImportMapping) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    standard_metadata = record.get("metadata")
    if standard_metadata not in (None, ""):
        parsed = _parse_json_object(standard_metadata, "metadata")
        metadata.update(parsed)

    if mapping.metadata_fields:
        for field in mapping.metadata_fields:
            if field == "metadata":
                continue
            value = _get_field(record, field)
            if value is not None:
                metadata[field] = value
        return metadata

    consumed = {
        mapping.id_field.split(".", maxsplit=1)[0],
        *(field.split(".", maxsplit=1)[0] for field in mapping.content_fields),
        "metadata",
        "embedding",
    }
    if mapping.collection_field:
        consumed.add(mapping.collection_field.split(".", maxsplit=1)[0])
    metadata.update(
        {key: value for key, value in record.items() if key not in consumed}
    )
    return metadata


def _get_field(record: Mapping[str, Any], dotted_name: str) -> Any:
    current: Any = record
    for part in dotted_name.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value).strip()


def _parse_json_object(value: Any, field_name: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ImportDataError(
                f"Field '{field_name}' must contain a JSON object"
            ) from exc
    if not isinstance(value, Mapping):
        raise ImportDataError(f"Field '{field_name}' must be a JSON object")
    return dict(value)


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ImportDataError(f"Expected a JSON object at {location}")
    return dict(value)
