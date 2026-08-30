"""Scope document IDs by collection.

Revision ID: 005_add_collections
Revises: 004_add_metadata_index
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005_add_collections"
down_revision: str | Sequence[str] | None = "004_add_metadata_index"
branch_labels = None
depends_on = None

TABLE = "documents"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "collection",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
    )
    op.drop_constraint("documents_pkey", TABLE, type_="primary")
    op.create_primary_key("documents_pkey", TABLE, ["collection", "id"])


def downgrade() -> None:
    # Creating the ID-only key intentionally fails without changing data when
    # two collections contain the same ID.
    op.drop_constraint("documents_pkey", TABLE, type_="primary")
    op.create_primary_key("documents_pkey", TABLE, ["id"])
    op.drop_column(TABLE, "collection")
