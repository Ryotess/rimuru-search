from types import SimpleNamespace

import pytest

from scripts.check_models import validate_rerank_order


def test_validate_rerank_order_accepts_relevant_document_first():
    response = SimpleNamespace(
        results=[
            {"index": 0, "relevance_score": 0.9},
            {"index": 1, "relevance_score": 0.1},
        ]
    )

    assert validate_rerank_order(response) == (0.9, 0.1)


def test_validate_rerank_order_rejects_reversed_scores():
    response = SimpleNamespace(
        results=[
            {"index": 1, "relevance_score": 0.8},
            {"index": 0, "relevance_score": 0.2},
        ]
    )

    with pytest.raises(RuntimeError, match="relevant document"):
        validate_rerank_order(response)
