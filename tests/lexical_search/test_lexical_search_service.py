from unittest.mock import patch

import pytest

from src.lexical_search.exceptions import LexicalSearchException
from src.lexical_search.service import lexical_search_by_content


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, responses=None, fail=False):
        self.responses = list(responses or [[]])
        self.fail = fail
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        if self.fail:
            raise RuntimeError("db error")
        return FakeResult(self.responses.pop(0))


def _document(document_id: str):
    return type(
        "D",
        (),
        {
            "collection": "default",
            "id": document_id,
            "content": f"Searchable content for {document_id}",
            "metadata_json": {"source": "test"},
        },
    )


@pytest.mark.asyncio
async def test_lexical_search_returns_empty_when_too_short():
    session = FakeSession()
    hits = await lexical_search_by_content(session, " ", top_k=5)
    assert hits == []
    assert session.statements == []


@pytest.mark.asyncio
async def test_bm25_is_the_default_backend():
    document = _document("document-3")
    session = FakeSession(responses=[[(document, 0.9)]])

    hits = await lexical_search_by_content(session, "power", top_k=1)

    assert hits == [
        {
            "collection": "default",
            "id": "document-3",
            "content": "Searchable content for document-3",
            "metadata": {"source": "test"},
            "rank": 0.9,
        }
    ]
    sql = str(session.statements[0])
    assert "<@>" in sql
    assert "to_bm25query" in sql
    assert "documents_content_bm25_idx" in sql


@pytest.mark.asyncio
async def test_fts_backend_remains_available():
    session = FakeSession()

    with patch("src.config.app_settings.search_lexical_backend", "fts"):
        await lexical_search_by_content(session, "power")

    sql = str(session.statements[0])
    assert "ts_rank_cd" in sql
    assert "@@" in sql
    assert "<@>" not in sql


@pytest.mark.asyncio
async def test_lexical_search_wraps_errors():
    session = FakeSession(fail=True)
    with pytest.raises(LexicalSearchException):
        await lexical_search_by_content(session, "power")


@pytest.mark.asyncio
async def test_lexical_search_applies_metadata_and_collection_filters():
    session = FakeSession()

    await lexical_search_by_content(
        session,
        "power",
        metadata_filter={"language": "en"},
        collection="articles",
    )

    sql = str(session.statements[0])
    assert "metadata_json" in sql
    assert "collection" in sql


@pytest.mark.asyncio
async def test_fuzzy_search_fuses_rankings_instead_of_raw_scores():
    first = _document("first")
    second = _document("second")
    session = FakeSession(
        responses=[
            [(first, 7.5), (second, 3.0)],
            [(second, 0.9), (first, 0.8)],
        ]
    )

    hits = await lexical_search_by_content(
        session,
        "power",
        top_k=2,
        use_fuzzy=True,
    )

    assert len(session.statements) == 2
    assert [hit["id"] for hit in hits] == ["first", "second"]
    assert hits[0]["rank"] == pytest.approx(hits[1]["rank"])
    assert "similarity" in str(session.statements[1])
