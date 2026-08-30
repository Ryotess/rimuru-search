"""Add pg_textsearch BM25 retrieval.

Revision ID: 006_add_bm25_search
Revises: 005_add_collections
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006_add_bm25_search"
down_revision: str | Sequence[str] | None = "005_add_collections"
branch_labels = None
depends_on = None

TABLE = "documents"
INDEX = "documents_content_bm25_idx"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch;")
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX}
            ON {TABLE}
            USING bm25 ((immutable_unaccent(content)))
            WITH (text_config = 'simple');
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX};")
