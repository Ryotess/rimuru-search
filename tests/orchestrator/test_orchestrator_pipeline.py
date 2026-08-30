from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrator.schemas import RerankedHit, RRFHit, SearchRequest
from src.orchestrator.service.orchestrator import (
    _run_search_pipeline,
    orchestrate_search_with_details,
)
from src.orchestrator.service.rerank import rerank_candidates
from src.reranker.exceptions import RerankerException

FUSED_HITS = [
    RRFHit(
        id="document-1",
        content="First document",
        metadata={"source": "test"},
        rrf_score=0.2,
        vector_rank=1,
        vector_distance=0.01,
    ),
    RRFHit(
        id="document-2",
        content="Second document",
        rrf_score=0.15,
        lexical_rank=1,
        lexical_score=0.9,
    ),
]

RERANKED_HITS = [
    RerankedHit(**FUSED_HITS[0].model_dump(), rerank_score=0.9),
    RerankedHit(**FUSED_HITS[1].model_dump(), rerank_score=0.5),
]


def _patch_pipeline_io():
    """Stub out embedding / vector / lexical / fusion with deterministic values."""
    return (
        patch(
            "src.orchestrator.service.orchestrator.generate_query_vector",
            new=AsyncMock(return_value=[0.1, 0.2, 0.3]),
        ),
        patch(
            "src.orchestrator.service.orchestrator.fetch_vector_hits",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "src.orchestrator.service.orchestrator.fetch_lexical_hits",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "src.orchestrator.service.orchestrator.fuse_search_hits",
            return_value=FUSED_HITS,
        ),
    )


@pytest.mark.asyncio
async def test_pipeline_invokes_rerank():
    embed, vec, lex, fuse = _patch_pipeline_io()
    with (
        embed,
        vec as vector_mock,
        lex as lexical_mock,
        fuse,
        patch(
            "src.orchestrator.service.orchestrator.rerank_candidates",
            new=AsyncMock(return_value=RERANKED_HITS),
        ) as rerank_mock,
    ):
        req = SearchRequest(query="hello", collection="articles")
        result = await _run_search_pipeline(req, session=None)

    rerank_mock.assert_awaited_once()
    assert vector_mock.await_args.kwargs["collection"] == "articles"
    assert lexical_mock.await_args.kwargs["collection"] == "articles"
    assert [hit.id for hit in result] == ["document-1", "document-2"]


@pytest.mark.asyncio
async def test_orchestrate_search_with_details_returns_hits():
    embed, vec, lex, fuse = _patch_pipeline_io()
    with (
        embed,
        vec,
        lex,
        fuse,
        patch(
            "src.orchestrator.service.orchestrator.rerank_candidates",
            new=AsyncMock(return_value=RERANKED_HITS),
        ),
    ):
        req = SearchRequest(query="hello")
        resp = await orchestrate_search_with_details(req, session=None)

    assert len(resp.hits) == 2


@pytest.mark.asyncio
async def test_reranker_failure_falls_back_to_fused_hits():
    with patch(
        "src.orchestrator.service.rerank.aget_rerank_result",
        new=AsyncMock(side_effect=RerankerException("unavailable")),
    ):
        result = await rerank_candidates("hello", FUSED_HITS, requested_top_n=1)

    assert [hit.id for hit in result] == ["document-1"]
    assert result[0].rerank_score is None


@pytest.mark.asyncio
async def test_reranking_can_be_disabled_in_config(monkeypatch):
    monkeypatch.setattr(
        "src.orchestrator.service.rerank.app_settings.search_enable_rerank", False
    )
    with patch(
        "src.orchestrator.service.rerank.aget_rerank_result", new=AsyncMock()
    ) as rerank:
        result = await rerank_candidates("hello", FUSED_HITS, requested_top_n=2)

    rerank.assert_not_awaited()
    assert [hit.id for hit in result] == ["document-1", "document-2"]
