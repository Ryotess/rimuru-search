from typing import Any

from pydantic import BaseModel, Field

from src.config import app_settings
from src.lexical_search.config import lexical_settings


class FTSQuery(BaseModel):
    collection: str = Field(
        default=app_settings.document_default_collection, min_length=1
    )
    query: str = Field(
        ...,
        min_length=lexical_settings.min_query_length,
        description="Lexical query to run against document content.",
    )
    top_k: int = Field(
        default=lexical_settings.top_k_default,
        ge=1,
        le=lexical_settings.top_k_max,
        description="Number of matches to return (lexical ranked).",
    )
    document_ids: list[str] | None = Field(
        default=None,
        description="Optional document IDs to restrict the search to.",
    )
    metadata_filter: dict[str, Any] | None = None
    use_fuzzy: bool = Field(
        default=False,
        description=(
            "Add trigram typo recovery to the configured BM25 or FTS backend."
        ),
    )
    min_similarity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Optional trigram similarity floor for fuzzy matching. "
            "Defaults to server config if omitted."
        ),
    )


class LexicalHit(BaseModel):
    collection: str
    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    rank: float | None = None
