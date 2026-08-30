# src/lexical_search/config.py
from src.config import app_settings


class _LexicalSettingsProxy:
    """Proxy that re-exports lexical search fields from app_settings."""

    @property
    def backend(self) -> str:
        return app_settings.search_lexical_backend

    @property
    def top_k_default(self) -> int:
        return app_settings.lexical_top_k_default

    @property
    def top_k_max(self) -> int:
        return app_settings.lexical_top_k_max

    @property
    def min_query_length(self) -> int:
        return app_settings.lexical_min_query_length

    @property
    def trgm_min_similarity(self) -> float:
        return app_settings.lexical_trgm_min_similarity

    @property
    def enable_fuzzy(self) -> bool:
        return app_settings.lexical_enable_fuzzy


lexical_settings = _LexicalSettingsProxy()
