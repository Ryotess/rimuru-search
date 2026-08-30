import json

import pytest

from src.importing.reader import (
    ImportDataError,
    ImportMapping,
    detect_format,
    iter_raw_records,
    map_record,
    parse_field_list,
)


def test_maps_arbitrary_fields_and_preserves_unused_metadata():
    record = {
        "sku": "item-1",
        "title": "Battery storage",
        "description": "Balances the electricity grid",
        "category": "energy",
    }
    mapping = ImportMapping(
        id_field="sku",
        content_fields=("title", "description"),
    )

    result = map_record(record, mapping, 1)

    assert result == {
        "collection": "default",
        "id": "item-1",
        "content": "Battery storage\n\nBalances the electricity grid",
        "metadata": {"category": "energy"},
    }


def test_standard_metadata_object_is_flattened():
    result = map_record(
        {"id": "1", "content": "Hello", "metadata": {"language": "en"}},
        ImportMapping(),
        1,
    )
    assert result["metadata"] == {"language": "en"}


def test_standard_collection_field_overrides_default():
    result = map_record(
        {"collection": "articles", "id": "1", "content": "Hello"},
        ImportMapping(collection="fallback"),
        1,
    )
    assert result["collection"] == "articles"
    assert "collection" not in result["metadata"]


def test_csv_metadata_json_string_is_parsed():
    result = map_record(
        {"id": "1", "content": "Hello", "metadata": '{"language":"en"}'},
        ImportMapping(),
        1,
    )
    assert result["metadata"] == {"language": "en"}


def test_stable_ids_can_be_generated():
    record = {"title": "No explicit ID"}
    mapping = ImportMapping(content_fields=("title",), generate_ids=True)
    first = map_record(record, mapping, 1)
    second = map_record(record, mapping, 2)
    assert first["id"] == second["id"]
    assert first["id"].startswith("doc-")


def test_collection_can_come_from_each_record():
    mapping = ImportMapping(
        collection="fallback",
        collection_field="tenant",
        content_fields=("content",),
    )
    result = map_record(
        {"tenant": "knowledge-base", "id": "1", "content": "Hello"},
        mapping,
        1,
    )
    assert result["collection"] == "knowledge-base"
    assert "tenant" not in result["metadata"]


def test_missing_id_has_actionable_error():
    with pytest.raises(ImportDataError, match="IMPORT_GENERATE_IDS"):
        map_record({"content": "hello"}, ImportMapping(), 1)


def test_json_accepts_array_and_documents_envelope(tmp_path):
    array_path = tmp_path / "array.json"
    array_path.write_text(json.dumps([{"id": "1"}, {"id": "2"}]))
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps({"documents": [{"id": "3"}]}))

    assert [row[1]["id"] for row in iter_raw_records(array_path, "json")] == [
        "1",
        "2",
    ]
    assert [row[1]["id"] for row in iter_raw_records(envelope_path, "json")] == ["3"]


def test_jsonl_reports_invalid_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":"1"}\nnot-json\n')

    with pytest.raises(ImportDataError, match="line 2"):
        list(iter_raw_records(path, "jsonl"))


def test_detects_ndjson_and_parses_field_lists(tmp_path):
    assert detect_format(tmp_path / "documents.ndjson") == "jsonl"
    assert parse_field_list(" title, description, ") == ("title", "description")
