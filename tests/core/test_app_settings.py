# tests/core/test_app_settings.py
"""Tests for the unified AppSettings class."""

import pytest
from pydantic import ValidationError


class TestAppSettingsDefaults:
    """Verify default values match the original module configs."""

    def test_global_hnsw_ef_search_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.global_hnsw_ef_search == 200

    def test_global_hnsw_iterative_scan_default(self):
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.global_hnsw_iterative_scan == "strict_order"

    def test_global_db_pool_size_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.global_db_pool_size == 5

    def test_global_db_max_overflow_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.global_db_max_overflow == 10

    def test_global_db_pool_timeout_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.global_db_pool_timeout == 30

    def test_global_db_pool_recycle_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.global_db_pool_recycle == 1800

    def test_embed_embedding_model_default(self, monkeypatch):
        """The bundled model preserves the database's 1,024-vector dimension."""
        monkeypatch.delenv("EMBEDDING_REQUEST_MODEL", raising=False)
        monkeypatch.delenv("EMBEDDING_MODEL_ID", raising=False)
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert (
            s.embed_embedding_model == "hosted_vllm/mixedbread-ai/mxbai-embed-large-v1"
        )

    def test_reranker_reranker_model_default(self, monkeypatch):
        """The bundled reranker is small enough for the local Compose demo."""
        monkeypatch.delenv("RERANKER_REQUEST_MODEL", raising=False)
        monkeypatch.delenv("RERANKER_MODEL_ID", raising=False)
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert (
            s.reranker_reranker_model
            == "hosted_vllm/cross-encoder/ms-marco-MiniLM-L6-v2"
        )

    def test_reranker_top_n_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.reranker_top_n == 10

    def test_reranker_max_document_length_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.reranker_max_document_length == 8192

    def test_vdb_embedding_dim_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.vdb_embedding_dim == 1024

    def test_lexical_top_k_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.lexical_top_k_default == 10

    def test_lexical_top_k_max_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.lexical_top_k_max == 100

    def test_lexical_min_query_length_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.lexical_min_query_length == 1

    def test_lexical_trgm_min_similarity_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.lexical_trgm_min_similarity == pytest.approx(0.05)

    def test_lexical_enable_fuzzy_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.lexical_enable_fuzzy is False

    def test_search_lexical_backend_defaults_to_bm25(self):
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.search_lexical_backend == "bm25"

    def test_cache_redis_url_default(self):
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.cache_redis_url is None

    def test_cors_defaults_are_local_and_credential_free(self):
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.cors_allowed_origins_list == ["http://localhost:3000"]
        assert s.cors_allow_credentials is False

    def test_cache_ttl_seconds_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.cache_ttl_seconds == 3600

    def test_cache_key_prefix_default(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.cache_key_prefix == "hybrid-search:search:v2"

    def test_source_api_documents_path_default(self, monkeypatch):
        monkeypatch.delenv("SOURCE_API_DOCUMENTS_PATH", raising=False)
        from src.config import AppSettings

        s = AppSettings()
        assert s.source_api_documents_path == "/v1/documents"

    def test_search_and_import_defaults(self, monkeypatch):
        for name in (
            "SEARCH_RRF_TOP_K_DEFAULT",
            "SEARCH_ENABLE_RERANK",
            "DOCUMENT_DEFAULT_COLLECTION",
            "IMPORT_CONTENT_FIELDS",
            "IMPORT_COLLECTION_FIELD",
            "IMPORT_MODE",
            "SEED_EMBED_BATCH_SIZE",
        ):
            monkeypatch.delenv(name, raising=False)
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.search_rrf_top_k_default == 15
        assert s.search_enable_rerank is True
        assert s.document_default_collection == "default"
        assert s.import_content_fields == "content"
        assert s.import_collection_field == "collection"
        assert s.import_mode == "upsert"
        assert s.seed_embed_batch_size == 256

    def test_model_request_names_derive_from_model_ids(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_REQUEST_MODEL", raising=False)
        monkeypatch.delenv("RERANKER_REQUEST_MODEL", raising=False)
        monkeypatch.setenv("EMBEDDING_MODEL_ID", "example/embedding-1024")
        monkeypatch.setenv("RERANKER_MODEL_ID", "example/reranker")
        from src.config import AppSettings

        settings = AppSettings(_env_file=None)

        assert settings.embed_embedding_model == "hosted_vllm/example/embedding-1024"
        assert settings.reranker_reranker_model == "hosted_vllm/example/reranker"

    def test_explicit_request_model_can_use_a_served_alias(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_MODEL_ID", "provider/model-source")
        monkeypatch.setenv("EMBEDDING_REQUEST_MODEL", "hosted_vllm/served-alias")
        from src.config import AppSettings

        settings = AppSettings(_env_file=None)

        assert settings.embed_embedding_model == "hosted_vllm/served-alias"


class TestAppSettingsRequired:
    """Verify required fields are read from env vars."""

    def test_global_database_url_from_env(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.global_database_url == "postgresql://example.com/db"

    def test_embed_hosted_vllm_api_base_from_env(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.embed_hosted_vllm_api_base == "http://localhost:5678/v1"

    def test_reranker_hosted_vllm_api_base_from_env(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.reranker_hosted_vllm_api_base == "http://localhost:5679"

    def test_source_api_base_url_from_env(self):
        from src.config import AppSettings

        s = AppSettings()
        assert s.source_api_base_url == "http://localhost:3000"


class TestAppSettingsLocalDefaults:
    """A fresh checkout can run local tooling before creating a .env file."""

    def test_connection_settings_have_local_defaults(self, monkeypatch):
        for name in (
            "GLOBAL_DATABASE_URL",
            "EMBED_HOSTED_VLLM_API_BASE",
            "RERANKER_HOSTED_VLLM_API_BASE",
            "SOURCE_API_BASE_URL",
        ):
            monkeypatch.delenv(name, raising=False)

        from src.config import AppSettings

        settings = AppSettings(_env_file=None)
        assert "localhost:5432" in settings.global_database_url
        assert settings.embed_hosted_vllm_api_base == "http://localhost:5678/v1"
        assert settings.reranker_hosted_vllm_api_base == "http://localhost:5679/v1"
        assert settings.source_api_base_url == "http://localhost:3000"


class TestAppSettingsValidation:
    """Verify validators and constraints."""

    def test_cache_ttl_seconds_ge_1(self):
        from src.config import AppSettings

        with pytest.raises(ValidationError):
            AppSettings(
                global_database_url="postgresql://x/db",
                embed_hosted_vllm_api_base="http://x",
                reranker_hosted_vllm_api_base="http://x",
                source_api_base_url="http://x",
                cache_ttl_seconds=0,
            )

    def test_reranker_top_n_ge_1(self):
        from src.config import AppSettings

        with pytest.raises(ValidationError):
            AppSettings(
                global_database_url="postgresql://x/db",
                embed_hosted_vllm_api_base="http://x",
                reranker_hosted_vllm_api_base="http://x",
                source_api_base_url="http://x",
                reranker_top_n=0,
            )

    def test_reranker_max_document_length_ge_1(self):
        from src.config import AppSettings

        with pytest.raises(ValidationError):
            AppSettings(
                global_database_url="postgresql://x/db",
                embed_hosted_vllm_api_base="http://x",
                reranker_hosted_vllm_api_base="http://x",
                source_api_base_url="http://x",
                reranker_max_document_length=0,
            )

    def test_reranker_max_document_length_field_validator(self):
        """The field_validator should reject negative values too."""
        from src.config import AppSettings

        with pytest.raises(ValidationError):
            AppSettings(
                global_database_url="postgresql://x/db",
                embed_hosted_vllm_api_base="http://x",
                reranker_hosted_vllm_api_base="http://x",
                source_api_base_url="http://x",
                reranker_max_document_length=-5,
            )


class TestAppSettingsEnvMapping:
    """Verify that env vars without prefix map to the correct fields."""

    def test_env_var_override(self, monkeypatch):
        """Setting an env var like VDB_EMBEDDING_DIM should map to vdb_embedding_dim."""
        monkeypatch.setenv("VDB_EMBEDDING_DIM", "512")
        from src.config import AppSettings

        s = AppSettings()
        assert s.vdb_embedding_dim == 512

    def test_lexical_env_override(self, monkeypatch):
        monkeypatch.setenv("LEXICAL_ENABLE_FUZZY", "true")
        from src.config import AppSettings

        s = AppSettings()
        assert s.lexical_enable_fuzzy is True

    def test_search_lexical_backend_env_override(self, monkeypatch):
        monkeypatch.setenv("SEARCH_LEXICAL_BACKEND", "fts")
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.search_lexical_backend == "fts"

    def test_search_lexical_backend_rejects_unknown_value(self):
        from src.config import AppSettings

        with pytest.raises(ValidationError):
            AppSettings(_env_file=None, search_lexical_backend="auto")

    def test_hnsw_iterative_scan_env_override(self, monkeypatch):
        monkeypatch.setenv("GLOBAL_HNSW_ITERATIVE_SCAN", "relaxed_order")
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.global_hnsw_iterative_scan == "relaxed_order"

    def test_hnsw_iterative_scan_rejects_unknown_value(self):
        from src.config import AppSettings

        with pytest.raises(ValidationError):
            AppSettings(_env_file=None, global_hnsw_iterative_scan="invalid")

    def test_cache_redis_url_env_override(self, monkeypatch):
        monkeypatch.setenv("CACHE_REDIS_URL", "redis://myhost:6379/1")
        from src.config import AppSettings

        s = AppSettings()
        assert s.cache_redis_url == "redis://myhost:6379/1"

    def test_cors_origins_parse_from_env(self, monkeypatch):
        monkeypatch.setenv(
            "CORS_ALLOWED_ORIGINS",
            "https://search.example, https://admin.example",
        )
        monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.cors_allowed_origins_list == [
            "https://search.example",
            "https://admin.example",
        ]
        assert s.cors_allow_credentials is True

    def test_source_api_documents_path_env_override(self, monkeypatch):
        monkeypatch.setenv("SOURCE_API_DOCUMENTS_PATH", "/searchable-records")
        from src.config import AppSettings

        s = AppSettings()
        assert s.source_api_documents_path == "/searchable-records"

    def test_search_and_import_env_overrides(self, monkeypatch):
        monkeypatch.setenv("SEARCH_RRF_TOP_K_DEFAULT", "7")
        monkeypatch.setenv("SEARCH_ENABLE_RERANK", "false")
        monkeypatch.setenv("DOCUMENT_DEFAULT_COLLECTION", "articles")
        monkeypatch.setenv("IMPORT_CONTENT_FIELDS", "title,description")
        monkeypatch.setenv("IMPORT_COLLECTION_FIELD", "dataset")
        monkeypatch.setenv("IMPORT_MODE", "replace")
        monkeypatch.setenv("SEED_EMBED_BATCH_SIZE", "32")
        from src.config import AppSettings

        s = AppSettings(_env_file=None)
        assert s.search_rrf_top_k_default == 7
        assert s.search_enable_rerank is False
        assert s.document_default_collection == "articles"
        assert s.import_content_fields == "title,description"
        assert s.import_collection_field == "dataset"
        assert s.import_mode == "replace"
        assert s.seed_embed_batch_size == 32


class TestAppSettingsSingleton:
    """Verify app_settings module-level instance exists."""

    def test_app_settings_instance_exists(self):
        from src.config import app_settings

        assert app_settings is not None

    def test_app_settings_is_app_settings_type(self):
        from src.config import AppSettings, app_settings

        assert isinstance(app_settings, AppSettings)


class TestGlobalSettingsUntouched:
    """Verify that GlobalSettings and global_settings still exist."""

    def test_global_settings_class_exists(self):
        from src.config import GlobalSettings

        assert GlobalSettings is not None

    def test_global_settings_instance_exists(self):
        from src.config import global_settings

        assert global_settings is not None
        assert global_settings.database_url == "postgresql://example.com/db"
