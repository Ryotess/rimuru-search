# src/reranker/config.py
from src.config import app_settings


class _RerankerSettingsProxy:
    """Proxy that re-exports reranker fields from app_settings."""

    @property
    def hosted_vllm_api_base(self) -> str:
        return app_settings.reranker_hosted_vllm_api_base

    @property
    def reranker_model(self) -> str:
        return app_settings.reranker_reranker_model

    @property
    def top_n(self) -> int:
        return app_settings.reranker_top_n

    @property
    def max_document_length(self) -> int:
        return app_settings.reranker_max_document_length


reranker_settings = _RerankerSettingsProxy()
