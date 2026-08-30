from types import SimpleNamespace

from src.orchestrator.schemas import RRFHit
from src.orchestrator.utils import (
    apply_rerank_scores,
    build_rerank_documents,
    fuse_hits_with_rrf,
)


def test_fuse_hits_with_rrf_prioritizes_combined_scores():
    vector_hits = [
        {
            "id": "document-a",
            "content": "First document",
            "metadata": {"kind": "article"},
            "distance": 0.1,
        },
        {
            "id": "document-b",
            "content": "Second document",
            "metadata": {},
            "distance": 0.2,
        },
    ]
    lexical_hits = [
        {
            "id": "document-b",
            "content": "Second document",
            "metadata": {},
            "rank": 0.8,
        },
        {
            "id": "document-c",
            "content": "Third document",
            "metadata": {},
            "rank": 0.7,
        },
    ]

    fused = fuse_hits_with_rrf(vector_hits, lexical_hits, k=60)

    assert [hit.id for hit in fused] == [
        "document-b",
        "document-a",
        "document-c",
    ]
    assert fused[0].rrf_score > fused[1].rrf_score > fused[2].rrf_score
    assert fused[0].lexical_rank == 1 and fused[0].vector_rank == 2


def test_build_and_apply_rerank_scores():
    hits = [
        RRFHit(
            id="document-1",
            content="First document",
            rrf_score=0.2,
            vector_rank=1,
            vector_distance=0.01,
            lexical_rank=None,
            lexical_score=None,
        ),
        RRFHit(
            id="document-2",
            content="Second document",
            rrf_score=0.15,
            vector_rank=None,
            vector_distance=None,
            lexical_rank=1,
            lexical_score=0.9,
        ),
    ]

    docs = build_rerank_documents(hits)
    assert docs == ["First document", "Second document"]

    mock_response = SimpleNamespace(
        results=[
            {"index": 1, "relevance_score": 0.92},
            {"index": 0, "relevance_score": 0.4},
        ]
    )

    reranked = apply_rerank_scores(hits, mock_response)

    assert [hit.id for hit in reranked] == ["document-2", "document-1"]
    assert reranked[0].rerank_score == 0.92
    assert reranked[1].rerank_score == 0.4


def test_fuse_hits_with_missing_ids_is_tolerant():
    vector_hits = [{"content": "no id", "distance": 0.2}]
    lexical_hits = [
        {
            "id": "document-with-id",
            "content": "Has id",
            "rank": 1.0,
        }
    ]

    fused = fuse_hits_with_rrf(vector_hits, lexical_hits)

    assert len(fused) == 1
    assert fused[0].id == "document-with-id"


def test_fusion_does_not_merge_same_id_from_different_collections():
    vector_hits = [
        {
            "collection": "articles",
            "id": "shared-id",
            "content": "Article",
            "distance": 0.1,
        }
    ]
    lexical_hits = [
        {
            "collection": "support",
            "id": "shared-id",
            "content": "Support document",
            "rank": 0.9,
        }
    ]

    fused = fuse_hits_with_rrf(vector_hits, lexical_hits)

    assert len(fused) == 2
    assert {hit.collection for hit in fused} == {"articles", "support"}
