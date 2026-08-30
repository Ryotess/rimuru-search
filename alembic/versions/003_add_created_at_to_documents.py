"""003 – add created_at to documents

Revision ID: 003_add_created_at
Revises: 002_add_seeding_tasks
Create Date: 2026-05-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_add_created_at"
down_revision: str | Sequence[str] | None = "002_add_seeding_tasks"
branch_labels = None
depends_on = None

TABLE = "documents"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("(now() AT TIME ZONE 'UTC')"),
        ),
    )


def downgrade() -> None:
    op.drop_column(TABLE, "created_at")
