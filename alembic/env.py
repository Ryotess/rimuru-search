# alembic/env.py
from __future__ import annotations

import os
import sys
from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine.url import make_url

from alembic import context

# Ensure models are imported so Alembic sees the tables.
from src import models  # noqa: F401
from src.config import global_settings
from src.database import Base

# --- Make sure we can import "src.*" when running from /alembic
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Alembic Config, reads alembic.ini
config = context.config

# Logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use DATABASE_URL env var even if alembic.ini has ${DATABASE_URL}
db_url = global_settings.database_url
if db_url:
    url_obj = make_url(db_url)
    if (
        url_obj.drivername.startswith("postgresql")
        and "+psycopg" not in url_obj.drivername
    ):
        url_obj = url_obj.set(drivername="postgresql+psycopg")
    # ConfigParser treats '%' as interpolation, so escape it for URLs.
    config.set_main_option(
        "sqlalchemy.url",
        url_obj.render_as_string(hide_password=False).replace("%", "%%"),
    )

# Metadata for autogenerate
target_metadata = Base.metadata

# Optional: better diffs (catch type/default/index changes)
AUTOGEN_KW = dict(
    target_metadata=target_metadata,
    compare_type=True,
    compare_server_default=True,
)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **AUTOGEN_KW,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        connection.execute(
            sa.text(
                "ALTER TABLE IF EXISTS alembic_version "
                "ALTER COLUMN version_num TYPE VARCHAR(128)"
            )
        )
        connection.commit()
        context.configure(connection=connection, **AUTOGEN_KW)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
