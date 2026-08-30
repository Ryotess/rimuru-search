from scripts.load_documents import _normalize_row


def test_dump_row_loader_preserves_collection():
    row = _normalize_row(
        {
            "collection": "articles",
            "id": "1",
            "content": "Searchable",
            "metadata": "{}",
            "embedding": "[0.1, 0.2]",
        }
    )
    assert row["collection"] == "articles"


def test_legacy_dump_row_uses_default_collection():
    row = _normalize_row(
        {
            "id": "1",
            "content": "Searchable",
            "metadata": "{}",
            "embedding": "[0.1, 0.2]",
        }
    )
    assert row["collection"] == "default"
