from types import SimpleNamespace

import numpy as np
import pytest

from src.vector_search.service import ann_search_by_vector


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.last_stmt = None

    async def execute(self, stmt):
        self.last_stmt = stmt
        return FakeResult(self.rows)


@pytest.mark.asyncio
async def test_ann_search_by_vector_returns_sorted_hits():
    document_1 = SimpleNamespace(
        collection="default",
        id="document-1",
        content="First document",
        metadata_json={"type": "article"},
        embedding=np.array([0.1, 0.2]),
    )
    document_2 = SimpleNamespace(
        collection="default",
        id="document-2",
        content="Second document",
        metadata_json={},
        embedding=np.array([0.3, 0.4]),
    )
    session = FakeSession(rows=[(document_1, 0.05), (document_2, 0.15)])

    hits = await ann_search_by_vector(session, [0.1, 0.2], top_k=2)

    assert hits == [
        {
            "collection": "default",
            "id": "document-1",
            "content": "First document",
            "metadata": {"type": "article"},
            "distance": 0.05,
        },
        {
            "collection": "default",
            "id": "document-2",
            "content": "Second document",
            "metadata": {},
            "distance": 0.15,
        },
    ]
    assert session.last_stmt is not None


@pytest.mark.asyncio
async def test_ann_search_applies_metadata_filter():
    session = FakeSession(rows=[])

    await ann_search_by_vector(
        session,
        [0.1, 0.2],
        top_k=2,
        metadata_filter={"language": "en"},
    )

    assert "metadata_json" in str(session.last_stmt)
    assert "collection" in str(session.last_stmt)
