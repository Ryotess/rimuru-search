from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from src.config import app_settings
from src.database import Base
from src.vector_search.config import vdb_settings


class Document(Base):
    __tablename__ = "documents"

    collection: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        autoincrement=False,
        default=app_settings.document_default_collection,
        server_default=text("'default'"),
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True, autoincrement=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, immutable_unaccent(coalesce(content, '')))",
            persisted=True,
        ),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(vdb_settings.embedding_dim), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.timezone("UTC", func.now()),
    )


__all__ = ["Document"]
