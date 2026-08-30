# src/vector_search/config.py
from src.config import app_settings


class _VDBSettingsProxy:
    """Proxy that re-exports vector DB fields from app_settings."""

    @property
    def embedding_dim(self) -> int:
        return app_settings.vdb_embedding_dim


vdb_settings = _VDBSettingsProxy()
