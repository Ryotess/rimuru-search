# src/orchestrator/schemas.py
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

from src.config import app_settings


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language query text")
    collection: str = Field(
        default=app_settings.document_default_collection,
        min_length=1,
        description="Collection namespace searched by both retrieval branches.",
    )
    document_ids: list[str] | None = Field(
        default=None,
        description="Optional document IDs to restrict both retrieval branches.",
    )
    metadata_filter: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional JSON object that stored metadata must contain. "
            'For example: {"language":"en","category":"guide"}.'
        ),
    )
    vector_top_k: int = Field(
        app_settings.search_vector_top_k_default,
        ge=1,
        le=200,
        description=(
            "ANN candidates fetched before fusion. Higher values can improve "
            "semantic recall at the cost of more database work."
        ),
    )
    lexical_top_k: int = Field(
        app_settings.search_lexical_top_k_default,
        ge=1,
        le=200,
        description=(
            "BM25 or PostgreSQL FTS candidates fetched before fusion. Higher values "
            "can improve exact-match recall at the cost of more database work."
        ),
    )
    use_fuzzy: bool = Field(
        default=app_settings.search_use_fuzzy_default,
        description=(
            "Enable trigram matching for typos and spelling variations in "
            "addition to the configured lexical backend."
        ),
    )
    min_similarity: float | None = Field(
        default=app_settings.search_min_similarity_default,
        ge=0.0,
        le=1.0,
        description=(
            "Trigram similarity floor used only when fuzzy matching is enabled. "
            "Lower values improve recall but can introduce noisier matches."
        ),
    )
    rrf_top_k: int = Field(
        app_settings.search_rrf_top_k_default,
        ge=1,
        le=100,
        description=(
            "Fused candidates retained and passed to the reranker. Higher values "
            "can improve recall but increase cross-encoder work."
        ),
    )
    rerank_top_n: int = Field(
        app_settings.search_rerank_top_n_default,
        ge=1,
        le=200,
        description=(
            "Final results returned after reranking, capped by available fused "
            "candidates. The reranker considers up to rrf_top_k candidates."
        ),
    )
    bypass_cache: bool = Field(
        default=False,
        description=(
            "When true, skip reading the cache but still write to it. "
            "Useful for evaluation runs that must observe fresh pipeline output."
        ),
    )


class RRFHit(BaseModel):
    collection: str = app_settings.document_default_collection
    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    rrf_score: float = Field(..., ge=0)
    vector_rank: int | None = Field(
        None, description="1-indexed rank from vector search (lower distance = better)"
    )
    vector_distance: float | None = None
    lexical_rank: int | None = Field(
        None, description="1-indexed rank from the configured lexical backend"
    )
    lexical_score: float | None = Field(
        None,
        description=(
            "Backend-specific lexical score; higher is better, but values are not "
            "comparable across BM25, FTS, or fuzzy-fused searches."
        ),
    )


class RerankedHit(RRFHit):
    rerank_score: float | None = Field(
        default=None,
        description=(
            "Cross-encoder relevance score. Null when reranking is disabled or "
            "the optional reranker is temporarily unavailable."
        ),
    )


class SearchIdsResponse(BaseModel):
    query: str
    collection: str = app_settings.document_default_collection
    document_ids: list[str] = Field(
        default_factory=list,
        description="Document IDs ordered by hybrid retrieval and reranking.",
    )


class SearchResponse(BaseModel):
    query: str
    collection: str = app_settings.document_default_collection
    hits: list[RerankedHit] = Field(  # type: ignore[pydantic-alias]  # Backward-compatible input aliases are intentional.
        default_factory=list,
        validation_alias=AliasChoices("hits", "reranked_hits"),
        description="Ranked documents with content, metadata, and retrieval scores.",
    )

    @property
    def reranked_hits(self) -> list[RerankedHit]:
        """Compatibility accessor for callers of the former details response."""
        return self.hits


# Kept as a source-compatible import alias while /v1/search/details is deprecated.
SearchDetailResponse = SearchResponse
