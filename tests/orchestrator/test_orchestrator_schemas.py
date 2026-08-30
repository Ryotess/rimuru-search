from src.orchestrator.schemas import (
    RerankedHit,
    SearchDetailResponse,
    SearchIdsResponse,
    SearchRequest,
)


def test_search_request_defaults():
    req = SearchRequest(query="hello")
    assert req.query == "hello"
    assert req.collection == "default"
    assert req.bypass_cache is False


def test_search_response_holds_results():
    resp = SearchIdsResponse(query="hello", document_ids=["a", "b"])
    assert resp.document_ids == ["a", "b"]


def test_search_detail_response_holds_hits():
    hit = RerankedHit(
        id="document-1",
        content="First document",
        rrf_score=0.1,
        rerank_score=0.1,
    )
    resp = SearchDetailResponse(query="hello", reranked_hits=[hit])
    assert len(resp.hits) == 1
    assert resp.model_dump() == {
        "query": "hello",
        "collection": "default",
        "hits": [hit.model_dump()],
    }


def test_search_request_accepts_metadata_filter():
    req = SearchRequest(query="hello", metadata_filter={"language": "en"})
    assert req.metadata_filter == {"language": "en"}


def test_search_request_accepts_collection():
    req = SearchRequest(query="hello", collection="support")
    assert req.collection == "support"
