# src/orchestrator/utils.py
from collections.abc import Iterable
from typing import Any

from src.config import app_settings
from src.embedding.schemas import EmbeddingResponse
from src.orchestrator.constants import RRF_K
from src.orchestrator.exceptions import EmbeddingParseException
from src.orchestrator.schemas import RerankedHit, RRFHit
from src.reranker.schemas import RerankResponse


def _extract_raw_embedding(entry: object) -> Iterable[Any] | None:
    """
    Pull an embedding payload from either a dict or object.
    """
    if isinstance(entry, dict):
        return entry.get("embedding")
    return getattr(entry, "embedding", None)


def extract_embedding_vector(response: EmbeddingResponse) -> list[float]:
    """
    Pull the first embedding vector from a LiteLLM EmbeddingResponse.
    """
    if not getattr(response, "data", None):
        raise EmbeddingParseException("Embedding response contained no data")

    first = response.data[0]
    vector = _extract_raw_embedding(first)

    if vector is None:
        raise EmbeddingParseException("Embedding vector missing from response")

    if not isinstance(vector, Iterable):
        raise EmbeddingParseException("Embedding vector is not iterable")

    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError) as exc:
        raise EmbeddingParseException(
            "Embedding vector contained a non-numeric value"
        ) from exc


def _ensure_hit_defaults(hit: dict[str, Any]) -> dict[str, Any]:
    """
    Fill in RRF fields with defaults to keep fusion outputs consistent.
    """
    return {
        "collection": str(
            hit.get("collection") or app_settings.document_default_collection
        ),
        "id": str(hit.get("id") or ""),
        "content": hit.get("content") or "",
        "metadata": hit.get("metadata") or {},
        "rrf_score": 0.0,
        "vector_rank": None,
        "vector_distance": None,
        "lexical_rank": None,
        "lexical_score": None,
    }


def fuse_hits_with_rrf(
    vector_hits: list[dict[str, Any]],
    lexical_hits: list[dict[str, Any]],
    k: int = RRF_K,
) -> list[RRFHit]:
    """
    Combine vector and lexical hits with Reciprocal Rank Fusion.
    Uses the 1-indexed rank position from each source to compute scores.
    """
    fused: dict[str, dict[str, Any]] = {}

    for idx, hit in enumerate(vector_hits):
        document_id = str(hit.get("id") or "")
        if not document_id:
            continue
        collection = hit.get("collection") or app_settings.document_default_collection
        key = f"{collection}\0{document_id}"
        entry = fused.setdefault(key, _ensure_hit_defaults(hit))
        entry["vector_rank"] = idx + 1
        entry["vector_distance"] = hit.get("distance")
        entry["rrf_score"] += 1 / (k + idx + 1)

    for idx, hit in enumerate(lexical_hits):
        document_id = str(hit.get("id") or "")
        if not document_id:
            continue
        collection = hit.get("collection") or app_settings.document_default_collection
        key = f"{collection}\0{document_id}"
        entry = fused.setdefault(key, _ensure_hit_defaults(hit))
        entry["lexical_rank"] = idx + 1
        entry["lexical_score"] = hit.get("rank")
        entry["rrf_score"] += 1 / (k + idx + 1)

    sorted_hits = sorted(
        fused.values(), key=lambda item: item["rrf_score"], reverse=True
    )
    return [RRFHit(**hit) for hit in sorted_hits]


def build_rerank_documents(hits: list[RRFHit]) -> list[str]:
    """
    Convert fused hits into short text snippets for the reranker.
    """
    return [hit.content for hit in hits]


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    """
    Safe getter for dicts or objects with a fallback.
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def apply_rerank_scores(
    hits: list[RRFHit], rerank_response: RerankResponse
) -> list[RerankedHit]:
    """
    Map reranker scores back onto the fused candidates.
    """
    results = getattr(rerank_response, "results", None)
    if not results:
        return []

    indexed_hits = {idx: hit for idx, hit in enumerate(hits)}
    reranked_hits: list[RerankedHit] = []

    for res in results:
        hit_idx = _get_attr(res, "index")
        score = _get_attr(res, "relevance_score")
        if hit_idx is None or score is None:
            continue
        base_hit = indexed_hits.get(int(hit_idx))
        if base_hit is None:
            continue
        reranked_hits.append(
            RerankedHit(**base_hit.model_dump(), rerank_score=float(score))
        )

    return reranked_hits
