"""001 – create documents with lexical and vector indexes

Revision ID: 001_create_documents
Revises:
Create Date: 2025-12-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

# --- config ---
TABLE = "documents"
DIM = 1024
TSV_COLUMN = "content_tsv"
GIN_INDEX = f"{TABLE}_{TSV_COLUMN}_gin_idx"
HNSW_INDEX = f"{TABLE}_embedding_hnsw_idx"
TRGM_INDEX = f"{TABLE}_content_trgm_idx"

# revision identifiers
revision: str = "001_create_documents"
down_revision: str | Sequence[str] | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions and helper function (idempotent).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION immutable_unaccent(text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
            SELECT public.unaccent($1);
        $$;
        """
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_exists = TABLE in inspector.get_table_names()

    # Core table schema.
    if not table_exists:
        op.create_table(
            TABLE,
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "metadata_json",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                TSV_COLUMN,
                postgresql.TSVECTOR(),
                sa.Computed(
                    "to_tsvector('simple'::regconfig, immutable_unaccent(coalesce(content, '')))",
                    persisted=True,
                ),
                nullable=False,
            ),
            sa.Column("embedding", Vector(DIM), nullable=False),
        )

    # Text search + trigram + HNSW (concurrent indexes must run outside txn).
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {GIN_INDEX}
            ON {TABLE}
            USING gin ({TSV_COLUMN});
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {TRGM_INDEX}
            ON {TABLE} USING gin (immutable_unaccent(content) gin_trgm_ops);
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {HNSW_INDEX}
            ON {TABLE} USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 200);
            """
        )

    op.execute(f"ANALYZE {TABLE};")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {HNSW_INDEX};")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {TRGM_INDEX};")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {GIN_INDEX};")
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION IF EXISTS immutable_unaccent(text);")
