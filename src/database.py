# src/database.py
from loguru import logger
from sqlalchemy import event, text
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import AsyncAdaptedQueuePool

from src.config import global_settings


class Base(DeclarativeBase):
    pass


_TARGET_URL = global_settings.database_url


def _as_async_url(url: str) -> URL:
    """Normalize PostgreSQL URLs to psycopg without rendering credentials."""
    db_url = make_url(url)
    if (
        db_url.drivername.startswith("postgresql")
        and "+psycopg" not in db_url.drivername
    ):
        db_url = db_url.set(drivername="postgresql+psycopg")
    return db_url


def _is_local(db_url) -> bool:
    """Return whether the database host is a known local development target."""
    host = db_url.host or ""
    return host in {"localhost", "127.0.0.1", "db", "postgres"}


def _has_explicit_ssl(db_url) -> bool:
    """Return whether the connection URL already declares an SSL policy."""
    return any(
        key in (db_url.query or {})
        for key in ("ssl", "sslmode", "sslrootcert", "sslcert", "sslkey")
    )


def _create_engine(url: str):
    db_url = _as_async_url(url)

    # Require transport encryption for non-local databases unless the operator
    # already supplied a more specific psycopg SSL policy.
    if not _is_local(db_url) and not _has_explicit_ssl(db_url):
        query_params = dict(db_url.query)
        query_params["sslmode"] = "require"
        db_url = db_url.set(query=query_params)

    # Disabling server-side prepared statements keeps transaction-mode
    # PgBouncer deployments compatible.
    connect_args = {"prepare_threshold": None}

    # Keep a small application-side queue pool to reduce connection setup cost.
    pool_kwargs = {
        "poolclass": AsyncAdaptedQueuePool,
        "pool_size": global_settings.db_pool_size,
        "max_overflow": global_settings.db_max_overflow,
        "pool_timeout": global_settings.db_pool_timeout,
        "pool_recycle": global_settings.db_pool_recycle,
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }

    # Passing a URL object avoids accidentally rendering credentials.
    return create_async_engine(db_url, **pool_kwargs)


def _setup_pool_listeners(async_engine):
    """Attach pool listeners through the AsyncEngine's sync adapter."""
    sync_eng = async_engine.sync_engine

    @event.listens_for(sync_eng, "checkout")
    def on_checkout(dbapi_conn, connection_record, connection_proxy):
        pool = async_engine.pool
        logger.debug(
            "Pool checkout - size: {}, checkedout: {}, overflow: {}",
            pool.size(),
            pool.checkedout(),
            pool.overflow(),
        )

    @event.listens_for(sync_eng, "checkin")
    def on_checkin(dbapi_conn, connection_record):
        pool = async_engine.pool
        logger.debug(
            "Pool checkin - size: {}, checkedout: {}",
            pool.size(),
            pool.checkedout(),
        )

    @event.listens_for(sync_eng, "connect")
    def on_connect(dbapi_conn, connection_record):
        logger.info("New database connection established")

    @event.listens_for(sync_eng, "invalidate")
    def on_invalidate(dbapi_conn, connection_record, exception):
        logger.warning("Connection invalidated: {}", exception)


engine = _create_engine(_TARGET_URL)

_setup_pool_listeners(engine)

SessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)


async def get_session():
    """Yield a database session with per-search pgvector tuning applied."""
    async with SessionLocal() as db:
        await db.execute(
            text(f"SET hnsw.ef_search = {global_settings.hnsw_ef_search};")
        )
        await db.execute(
            text(f"SET hnsw.iterative_scan = '{global_settings.hnsw_iterative_scan}';")
        )
        yield db


async def dispose_engines():
    """Dispose all application database connections."""
    await engine.dispose()
    logger.info("Database connections disposed")
