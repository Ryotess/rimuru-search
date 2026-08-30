from collections.abc import Sequence
from typing import Any

from loguru import logger
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import app_settings
from src.lexical_search.config import lexical_settings
from src.lexical_search.constants import BM25_INDEX_NAME, LEXICAL_FUSION_K
from src.lexical_search.exceptions import LexicalSearchException
from src.lexical_search.models import Document
from src.lexical_search.utils import normalize_query


def _apply_document_filters(
    stmt: Any,
    *,
    collection: str,
    document_ids: list[str] | None,
    metadata_filter: dict[str, Any] | None,
) -> Any:
    stmt = stmt.where(Document.collection == collection)
    if document_ids is not None:
        stmt = stmt.where(Document.id.in_(document_ids))
    if metadata_filter:
        stmt = stmt.where(Document.metadata_json.contains(metadata_filter))
    return stmt


def _serialize_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "collection": document.collection,
            "id": document.id,
            "content": document.content,
            "metadata": document.metadata_json,
            "rank": float(score) if score is not None else None,
        }
        for document, score in rows
    ]


def _fuse_lexical_hits(
    primary_hits: list[dict[str, Any]],
    fuzzy_hits: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Fuse lexical sources by rank because their raw score scales differ."""
    documents: dict[tuple[str, str], dict[str, Any]] = {}
    scores: dict[tuple[str, str], float] = {}
    best_ranks: dict[tuple[str, str], int] = {}

    for hits in (primary_hits, fuzzy_hits):
        for rank, hit in enumerate(hits, start=1):
            key = (hit["collection"], hit["id"])
            documents.setdefault(key, hit)
            scores[key] = scores.get(key, 0.0) + 1.0 / (LEXICAL_FUSION_K + rank)
            best_ranks[key] = min(best_ranks.get(key, rank), rank)

    ordered_keys = sorted(
        documents,
        key=lambda key: (
            -scores[key],
            best_ranks[key],
            key[0],
            key[1],
        ),
    )
    return [{**documents[key], "rank": scores[key]} for key in ordered_keys[:limit]]


async def _fetch_primary_hits(
    session: AsyncSession,
    normalized_query: str,
    limit: int,
    *,
    document_ids: list[str] | None,
    metadata_filter: dict[str, Any] | None,
    collection: str,
) -> list[dict[str, Any]]:
    if lexical_settings.backend == "bm25":
        # The indexed expression and index name must remain identical to the
        # Alembic/reseed definitions so pg_textsearch can plan an index scan.
        search_content = func.immutable_unaccent(Document.content)
        bm25_query = func.to_bm25query(
            normalized_query,
            literal_column(f"'{BM25_INDEX_NAME}'"),
        )
        bm25_distance = search_content.op("<@>")(bm25_query)
        positive_score = (-bm25_distance).label("rank")
        stmt = (
            select(Document, positive_score)
            .where(bm25_distance < 0.0)
            .order_by(bm25_distance.asc())
            .limit(limit)
        )
    else:
        ts_query = func.websearch_to_tsquery("simple", normalized_query)
        fts_rank = func.ts_rank_cd(Document.content_tsv, ts_query).label("rank")
        stmt = (
            select(Document, fts_rank)
            .where(Document.content_tsv.op("@@")(ts_query))
            .order_by(fts_rank.desc())
            .limit(limit)
        )

    stmt = _apply_document_filters(
        stmt,
        collection=collection,
        document_ids=document_ids,
        metadata_filter=metadata_filter,
    )
    rows = (await session.execute(stmt)).all()
    return _serialize_rows(rows)


async def _fetch_fuzzy_hits(
    session: AsyncSession,
    normalized_query: str,
    limit: int,
    *,
    min_similarity: float,
    document_ids: list[str] | None,
    metadata_filter: dict[str, Any] | None,
    collection: str,
) -> list[dict[str, Any]]:
    similarity_score = func.similarity(
        func.immutable_unaccent(Document.content), normalized_query
    ).label("rank")
    stmt = (
        select(Document, similarity_score)
        .where(similarity_score >= min_similarity)
        .order_by(similarity_score.desc())
        .limit(limit)
    )
    stmt = _apply_document_filters(
        stmt,
        collection=collection,
        document_ids=document_ids,
        metadata_filter=metadata_filter,
    )
    rows = (await session.execute(stmt)).all()
    return _serialize_rows(rows)


async def lexical_search_by_content(
    session: AsyncSession,
    query: str,
    top_k: int | None = None,
    document_ids: list[str] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    min_similarity: float | None = None,
    use_fuzzy: bool | None = None,
    collection: str = app_settings.document_default_collection,
) -> list[dict[str, Any]]:
    """Run the configured lexical backend with optional trigram typo recovery."""
    normalized_query = normalize_query(query)
    if len(normalized_query) < lexical_settings.min_query_length:
        logger.bind(length=len(normalized_query)).info(
            "Skipping lexical search: query below min length"
        )
        return []
    if document_ids is not None and not document_ids:
        logger.info("Skipping lexical search: document ID filter is empty")
        return []

    limit = top_k or lexical_settings.top_k_default
    fuzzy_enabled = lexical_settings.enable_fuzzy if use_fuzzy is None else use_fuzzy
    similarity_floor = (
        min_similarity
        if min_similarity is not None
        else lexical_settings.trgm_min_similarity
    )

    try:
        primary_hits = await _fetch_primary_hits(
            session,
            normalized_query,
            limit,
            document_ids=document_ids,
            metadata_filter=metadata_filter,
            collection=collection,
        )
        hits = primary_hits
        if fuzzy_enabled:
            fuzzy_hits = await _fetch_fuzzy_hits(
                session,
                normalized_query,
                limit,
                min_similarity=similarity_floor,
                document_ids=document_ids,
                metadata_filter=metadata_filter,
                collection=collection,
            )
            hits = _fuse_lexical_hits(primary_hits, fuzzy_hits, limit)
    except Exception as exc:
        raise LexicalSearchException("Lexical query failed") from exc

    logger.bind(
        backend=lexical_settings.backend,
        requested_top_k=limit,
        returned_hits=len(hits),
        filtered_ids=document_ids is not None,
        filtered_metadata=bool(metadata_filter),
        use_fuzzy=fuzzy_enabled,
        min_similarity=similarity_floor if fuzzy_enabled else None,
    ).info("Lexical search completed")
    return hits
