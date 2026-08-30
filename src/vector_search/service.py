# src/vector_search/service.py
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import app_settings
from src.vector_search.models import Document
from src.vector_search.utils import to_float32


async def ann_search_by_vector(
    session: AsyncSession,
    vector: list[float],
    top_k: int = 10,
    document_ids: list[str] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    collection: str = app_settings.document_default_collection,
) -> list[dict[str, Any]]:
    """
    Run a cosine-distance search over stored document embeddings.
    Args:
        session(AsyncSession): Active SQLAlchemy session for the vector database.
        vector(list[float]): Query embedding; length must match Document.embedding.
        top_k(int): Maximum number of nearest neighbors to return, default=10.
        document_ids(list[str]|None): Optional document ID whitelist.
        metadata_filter(dict|None): Optional JSONB containment filter.
        collection(str): Collection namespace to search.
    Returns:
        list[dict]: Top-K documents sorted by ascending cosine distance.
    """
    if document_ids is not None and len(document_ids) == 0:
        logger.info("Skipping vector ANN search: document ID filter is empty")
        return []

    logger.bind(
        requested_top_k=top_k,
        document_id_filters=len(document_ids or []),
        vector_dim=len(vector),
    ).debug("Starting vector ANN search")

    qvec = to_float32(vector)

    distance = Document.embedding.cosine_distance(qvec).label("distance")

    stmt = select(Document, distance).where(Document.collection == collection)
    if document_ids is not None:
        stmt = stmt.where(Document.id.in_(document_ids))
    if metadata_filter:
        stmt = stmt.where(Document.metadata_json.contains(metadata_filter))
    stmt = stmt.order_by(distance).limit(top_k)

    rows = (await session.execute(stmt)).all()

    logger.bind(
        requested_top_k=top_k,
        returned_hits=len(rows),
        filtered_ids=document_ids is not None,
        filtered_metadata=bool(metadata_filter),
    ).info("Vector ANN search completed")

    return [
        {
            "collection": document.collection,
            "id": document.id,
            "content": document.content,
            "metadata": document.metadata_json,
            "distance": float(dist),
        }
        for document, dist in rows
    ]
