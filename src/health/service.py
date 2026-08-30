# src/health/service.py
import asyncio
from inspect import isawaitable
from typing import Any

import httpx
from sqlalchemy import text

from src.cache.client import get_redis
from src.config import app_settings, global_settings
from src.database import engine
from src.lexical_search.constants import (
    BM25_INDEX_NAME,
    FTS_INDEX_NAME,
    TRGM_INDEX_NAME,
)


def get_pool_stats(eng):
    """Return current connection-pool statistics."""
    pool = eng.pool
    return {
        "size": pool.size(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
        "checked_in": pool.checkedin(),
    }


async def get_db_health() -> dict[str, Any]:
    """Check a real database round trip and include connection-pool statistics."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    stats = {"target_pool": get_pool_stats(engine)}

    max_connections = global_settings.db_pool_size + global_settings.db_max_overflow
    target_usage = stats["target_pool"]["checked_out"] / max_connections

    return {
        "status": "healthy" if target_usage < 0.8 else "degraded",
        "pools": stats,
        "usage_ratio": round(target_usage, 2),
    }


async def _extension_is_installed(connection: Any, name: str) -> bool:
    result = await connection.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = :extension_name)"
        ),
        {"extension_name": name},
    )
    return bool(result.scalar_one())


async def _index_is_ready(connection: Any, name: str) -> bool:
    result = await connection.execute(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_class AS index_class "
            "JOIN pg_index AS index_state ON index_state.indexrelid = index_class.oid "
            "WHERE index_class.oid = to_regclass(:index_name) "
            "AND index_state.indisvalid AND index_state.indisready"
            ")"
        ),
        {"index_name": f"public.{name}"},
    )
    return bool(result.scalar_one())


async def get_lexical_backend_health() -> str:
    """Validate extensions and indexes required by the configured backend."""
    backend = app_settings.search_lexical_backend
    primary_index = BM25_INDEX_NAME if backend == "bm25" else FTS_INDEX_NAME

    async with engine.connect() as connection:
        if backend == "bm25" and not await _extension_is_installed(
            connection, "pg_textsearch"
        ):
            return "unhealthy: missing_extension: pg_textsearch"
        if not await _extension_is_installed(connection, "pg_trgm"):
            return "unhealthy: missing_extension: pg_trgm"
        if not await _index_is_ready(connection, primary_index):
            return f"unhealthy: missing_index: {primary_index}"
        if not await _index_is_ready(connection, TRGM_INDEX_NAME):
            return f"unhealthy: missing_index: {TRGM_INDEX_NAME}"

    return f"healthy: {backend}"


def _upstream_health_url(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base}/health"


def _upstream_models_url(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def _upstream_model_id(configured_model: str) -> str:
    """Remove the LiteLLM provider prefix from a served model identifier."""
    return configured_model.removeprefix("hosted_vllm/")


async def _check_http_service(client: httpx.AsyncClient, api_base: str) -> str:
    response = await client.get(_upstream_health_url(api_base))
    response.raise_for_status()
    return "healthy"


async def _check_model_service(
    client: httpx.AsyncClient,
    api_base: str,
    configured_model: str,
) -> str:
    """Verify both connectivity and the model name used by search requests."""
    response = await client.get(_upstream_models_url(api_base))
    response.raise_for_status()
    payload = response.json()
    available_models = {
        item.get("id")
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    requested_model = _upstream_model_id(configured_model)
    if requested_model not in available_models:
        return f"unhealthy: model_not_found: {requested_model}"
    return "healthy"


async def get_readiness() -> dict[str, Any]:
    """Check every dependency required by the search request path."""
    checks: dict[str, str] = {}

    async def check_database() -> None:
        try:
            await get_db_health()
            checks["database"] = "healthy"
        except Exception as exc:
            checks["database"] = f"unhealthy: {type(exc).__name__}"

    async def check_lexical() -> None:
        try:
            checks["lexical"] = await get_lexical_backend_health()
        except Exception as exc:
            checks["lexical"] = f"unhealthy: {type(exc).__name__}"

    async with httpx.AsyncClient(timeout=5.0) as client:

        async def check_model(name: str, api_base: str, model: str) -> None:
            try:
                checks[name] = await _check_model_service(client, api_base, model)
            except Exception as exc:
                checks[name] = f"unhealthy: {type(exc).__name__}"

        model_checks = [
            check_model(
                "embedding",
                app_settings.embed_hosted_vllm_api_base,
                app_settings.embed_embedding_model,
            )
        ]
        if app_settings.search_enable_rerank:
            model_checks.append(
                check_model(
                    "reranker",
                    app_settings.reranker_hosted_vllm_api_base,
                    app_settings.reranker_reranker_model,
                )
            )
        else:
            checks["reranker"] = "disabled"

        await asyncio.gather(
            check_database(),
            check_lexical(),
            *model_checks,
        )

    redis = get_redis()
    if redis is None:
        checks["redis"] = "disabled"
    else:
        try:
            ping_result = redis.ping()
            if isawaitable(ping_result):
                await ping_result
            checks["redis"] = "healthy"
        except Exception as exc:
            checks["redis"] = f"unhealthy: {type(exc).__name__}"

    unhealthy = [value for value in checks.values() if value.startswith("unhealthy")]
    return {
        "status": "ready" if not unhealthy else "not_ready",
        "checks": checks,
    }
