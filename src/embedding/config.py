# src/embedding/config.py
from src.config import app_settings


class _EmbeddingSettingsProxy:
    """Proxy that re-exports embedding fields from app_settings."""

    @property
    def hosted_vllm_api_base(self) -> str:
        return app_settings.embed_hosted_vllm_api_base

    @property
    def embedding_model(self) -> str:
        return app_settings.embed_embedding_model


embedding_settings = _EmbeddingSettingsProxy()
