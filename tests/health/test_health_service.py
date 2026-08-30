from unittest.mock import AsyncMock, MagicMock, patch

from src.health.service import (
    _upstream_health_url,
    _upstream_model_id,
    _upstream_models_url,
    get_lexical_backend_health,
    get_readiness,
)


def test_upstream_health_url_removes_openai_v1_suffix():
    assert _upstream_health_url("http://embedding:8000/v1") == (
        "http://embedding:8000/health"
    )


def test_upstream_models_url_supports_base_with_or_without_v1():
    assert _upstream_models_url("http://embedding:8000/v1") == (
        "http://embedding:8000/v1/models"
    )
    assert _upstream_models_url("http://embedding:8000") == (
        "http://embedding:8000/v1/models"
    )


def test_upstream_model_id_removes_only_litellm_provider_prefix():
    assert _upstream_model_id("hosted_vllm/example/embedding-1024") == (
        "example/embedding-1024"
    )


async def test_bm25_readiness_requires_pg_textsearch():
    connection = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect.return_value = context

    with (
        patch("src.health.service.engine", mock_engine),
        patch(
            "src.health.service._extension_is_installed",
            AsyncMock(return_value=False),
        ),
    ):
        result = await get_lexical_backend_health()

    assert result == "unhealthy: missing_extension: pg_textsearch"


async def test_fts_readiness_uses_retained_indexes():
    connection = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect.return_value = context

    with (
        patch("src.health.service.engine", mock_engine),
        patch("src.health.service.app_settings.search_lexical_backend", "fts"),
        patch(
            "src.health.service._extension_is_installed",
            AsyncMock(return_value=True),
        ) as extension_check,
        patch(
            "src.health.service._index_is_ready",
            AsyncMock(return_value=True),
        ) as index_check,
    ):
        result = await get_lexical_backend_health()

    assert result == "healthy: fts"
    extension_check.assert_awaited_once_with(connection, "pg_trgm")
    assert [call.args[1] for call in index_check.await_args_list] == [
        "documents_content_tsv_gin_idx",
        "documents_content_trgm_idx",
    ]


async def test_readiness_reports_disabled_redis_without_failure():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "data": [
            {"id": "example/embedding-1024"},
            {"id": "example/reranker"},
        ]
    }

    with (
        patch("src.health.service.get_db_health", AsyncMock(return_value={})),
        patch(
            "src.health.service.get_lexical_backend_health",
            AsyncMock(return_value="healthy: bm25"),
        ),
        patch(
            "src.health.service.httpx.AsyncClient.get", AsyncMock(return_value=response)
        ),
        patch("src.health.service.get_redis", return_value=None),
    ):
        result = await get_readiness()

    assert result["status"] == "ready"
    assert result["checks"]["redis"] == "disabled"


async def test_readiness_skips_reranker_when_disabled():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": [{"id": "example/embedding-1024"}]}

    with (
        patch("src.health.service.get_db_health", AsyncMock(return_value={})),
        patch(
            "src.health.service.get_lexical_backend_health",
            AsyncMock(return_value="healthy: bm25"),
        ),
        patch(
            "src.health.service.httpx.AsyncClient.get",
            AsyncMock(return_value=response),
        ) as get,
        patch("src.health.service.get_redis", return_value=None),
        patch("src.health.service.app_settings.search_enable_rerank", False),
    ):
        result = await get_readiness()

    assert result["status"] == "ready"
    assert result["checks"]["reranker"] == "disabled"
    assert get.await_count == 1


async def test_readiness_reports_configured_model_mismatch():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": [{"id": "another-model"}]}

    with (
        patch("src.health.service.get_db_health", AsyncMock(return_value={})),
        patch(
            "src.health.service.get_lexical_backend_health",
            AsyncMock(return_value="healthy: bm25"),
        ),
        patch(
            "src.health.service.httpx.AsyncClient.get",
            AsyncMock(return_value=response),
        ),
        patch("src.health.service.get_redis", return_value=None),
        patch("src.health.service.app_settings.search_enable_rerank", False),
    ):
        result = await get_readiness()

    assert result["status"] == "not_ready"
    assert result["checks"]["embedding"].startswith("unhealthy: model_not_found")


async def test_readiness_reports_model_connection_failure():
    with (
        patch("src.health.service.get_db_health", AsyncMock(return_value={})),
        patch(
            "src.health.service.get_lexical_backend_health",
            AsyncMock(return_value="healthy: bm25"),
        ),
        patch(
            "src.health.service.httpx.AsyncClient.get",
            AsyncMock(side_effect=ConnectionError("offline")),
        ),
        patch("src.health.service.get_redis", return_value=None),
    ):
        result = await get_readiness()

    assert result["status"] == "not_ready"
    assert result["checks"]["embedding"].startswith("unhealthy")
    assert result["checks"]["reranker"].startswith("unhealthy")
