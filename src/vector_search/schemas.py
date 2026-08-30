# src/vector_search/schemas.py
from typing import Any

from pydantic import BaseModel, Field

from src.config import app_settings
from src.vector_search.config import vdb_settings


class ANNQueryByVector(BaseModel):
    collection: str = Field(
        default=app_settings.document_default_collection, min_length=1
    )
    vector: list[float] = Field(
        ...,
        min_length=vdb_settings.embedding_dim,
        max_length=vdb_settings.embedding_dim,
        description=f"Embedding vector of length {vdb_settings.embedding_dim}",
    )
    top_k: int = Field(10, ge=1, le=100)
    document_ids: list[str] | None = Field(
        default=None,
        description="Optional document IDs to restrict the search to.",
    )
    metadata_filter: dict[str, Any] | None = None


class DocumentHit(BaseModel):
    collection: str
    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    distance: float
