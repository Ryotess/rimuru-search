"""Add a JSONB containment index for search metadata filters.

Revision ID: 004_add_metadata_index
Revises: 003_add_created_at
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "004_add_metadata_index"
down_revision: str | Sequence[str] | None = "003_add_created_at"
branch_labels = None
depends_on = None

TABLE = "documents"
INDEX = "documents_metadata_json_gin_idx"


def upgrade() -> None:
    op.create_index(
        INDEX,
        TABLE,
        ["metadata_json"],
        postgresql_using="gin",
        postgresql_ops={"metadata_json": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
