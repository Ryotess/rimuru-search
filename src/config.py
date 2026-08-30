# src/config.py
import os
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Unified application settings consolidating all module configs."""

    env_file_path: ClassVar[str | Path] = os.getenv(
        "ENV_FILE", Path(__file__).parent.parent / ".env"
    )
    model_config = SettingsConfigDict(
        env_file=env_file_path if Path(env_file_path).exists() else None,
        extra="ignore",
    )

    # --- Global ---
    global_database_url: str = "postgresql://hybrid_search:local_dev_password@localhost:5432/hybrid_search"  # pragma: allowlist secret
    global_hnsw_ef_search: int = 200
    global_hnsw_iterative_scan: Literal["off", "strict_order", "relaxed_order"] = (
        "strict_order"
    )
    global_db_pool_size: int = 5
    global_db_max_overflow: int = 10
    global_db_pool_timeout: int = 30
    global_db_pool_recycle: int = 1800
    document_default_collection: str = "default"
    cors_allowed_origins: str = "http://localhost:3000"
    cors_allow_credentials: bool = False

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        """Return the comma-separated browser origins accepted by CORS."""
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    # --- Embedding ---
    embedding_model_id: str = "mixedbread-ai/mxbai-embed-large-v1"
    embed_hosted_vllm_api_base: str = "http://localhost:5678/v1"
    embedding_request_model: str | None = None

    @property
    def embed_embedding_model(self) -> str:
        return self.embedding_request_model or f"hosted_vllm/{self.embedding_model_id}"

    # --- Reranker ---
    reranker_model_id: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_hosted_vllm_api_base: str = "http://localhost:5679/v1"
    reranker_request_model: str | None = None

    @property
    def reranker_reranker_model(self) -> str:
        return self.reranker_request_model or f"hosted_vllm/{self.reranker_model_id}"

    reranker_top_n: int = Field(
        default=10, ge=1, description="Default top_n when request does not override"
    )
    reranker_max_document_length: int = Field(
        default=8192,
        ge=1,
        description="Maximum number of characters allowed per document",
    )

    @field_validator("reranker_max_document_length")
    def validate_max_doc_length(cls, value: int) -> int:
        if value < 1:
            raise ValueError("reranker_max_document_length must be positive")
        return value

    # --- Vector DB ---
    vdb_embedding_dim: int = 1024

    # --- Lexical Search ---
    lexical_top_k_default: int = 10
    lexical_top_k_max: int = 100
    lexical_min_query_length: int = 1
    lexical_trgm_min_similarity: float = 0.05
    lexical_enable_fuzzy: bool = False

    # --- Rimuru Search defaults ---
    search_lexical_backend: Literal["bm25", "fts"] = "bm25"
    search_vector_top_k_default: int = Field(default=100, ge=1, le=200)
    search_lexical_top_k_default: int = Field(default=100, ge=1, le=200)
    search_use_fuzzy_default: bool = False
    search_min_similarity_default: float = Field(default=0.2, ge=0.0, le=1.0)
    search_rrf_top_k_default: int = Field(default=15, ge=1, le=100)
    search_rerank_top_n_default: int = Field(default=3, ge=1, le=200)
    search_enable_rerank: bool = True

    # --- Docker Compose endpoint overrides ---
    # Empty model request names make the bundled model IDs the single source of
    # truth. These endpoint settings are also read by local tooling so it can
    # avoid starting a bundled service when an external one is configured.
    compose_embed_api_base: str | None = None
    compose_embed_request_model: str | None = None
    compose_reranker_api_base: str | None = None
    compose_reranker_request_model: str | None = None
    compose_cache_redis_url: str | None = "redis://redis:6379/0"

    # --- Ingestion ---
    seed_rows_per_chunk: int = Field(default=2_000, ge=1)
    seed_embed_batch_size: int = Field(default=256, ge=1)
    seed_db_batch_size: int = Field(default=2_000, ge=1)
    seed_max_embed_concurrency: int = Field(default=6, ge=1)

    # Direct JSON, JSONL, and CSV import defaults. Comma-separated field lists
    # keep these settings easy to express in a dotenv file.
    import_id_field: str = "id"
    import_content_fields: str = "content"
    import_metadata_fields: str = ""
    import_collection_field: str = "collection"
    import_generate_ids: bool = False
    import_mode: Literal["upsert", "replace"] = "upsert"
    import_file_encoding: str = "utf-8"
    import_csv_delimiter: str = ","

    @field_validator(
        "embedding_model_id",
        "reranker_model_id",
        "document_default_collection",
        "import_id_field",
        "import_content_fields",
        "import_file_encoding",
    )
    @classmethod
    def non_empty_required_setting(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("setting must not be empty")
        return value.strip()

    @field_validator("import_csv_delimiter")
    @classmethod
    def single_character_csv_delimiter(cls, value: str) -> str:
        if len(value) != 1:
            raise ValueError("import_csv_delimiter must be one character")
        return value

    # --- Cache ---
    cache_redis_url: str | None = Field(
        default=None,
        description=(
            "Redis connection URL (e.g. redis://host:6379/0). "
            "Empty = disable cache (pipeline runs every request)."
        ),
    )

    @field_validator(
        "cache_redis_url",
        "embedding_request_model",
        "reranker_request_model",
        "compose_embed_api_base",
        "compose_embed_request_model",
        "compose_reranker_api_base",
        "compose_reranker_request_model",
        "compose_cache_redis_url",
        mode="before",
    )
    @classmethod
    def empty_optional_url_or_model(cls, value: str | None) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    cache_ttl_seconds: int = Field(
        default=3600,
        ge=1,
        description="TTL (seconds) for cached search responses.",
    )
    cache_key_prefix: str = Field(
        default="hybrid-search:search:v2",
        description="Prefix for all cache keys; bump suffix to invalidate on schema change.",
    )

    # --- Source API ---
    source_api_base_url: str = "http://localhost:3000"
    source_api_documents_path: str = "/v1/documents"


app_settings = AppSettings()


class _GlobalSettingsProxy:
    """Proxy that re-exports global fields from app_settings."""

    @property
    def database_url(self) -> str:
        return app_settings.global_database_url

    @property
    def hnsw_ef_search(self) -> int:
        return app_settings.global_hnsw_ef_search

    @property
    def hnsw_iterative_scan(self) -> Literal["off", "strict_order", "relaxed_order"]:
        return app_settings.global_hnsw_iterative_scan

    @property
    def db_pool_size(self) -> int:
        return app_settings.global_db_pool_size

    @property
    def db_max_overflow(self) -> int:
        return app_settings.global_db_max_overflow

    @property
    def db_pool_timeout(self) -> int:
        return app_settings.global_db_pool_timeout

    @property
    def db_pool_recycle(self) -> int:
        return app_settings.global_db_pool_recycle


# Backward-compatible alias so ``from src.config import GlobalSettings`` keeps working.
GlobalSettings = _GlobalSettingsProxy

global_settings = _GlobalSettingsProxy()
