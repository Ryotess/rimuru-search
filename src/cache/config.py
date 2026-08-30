# src/cache/config.py
from src.config import app_settings


class _CacheSettingsProxy:
    """Proxy that re-exports cache fields from app_settings."""

    @property
    def redis_url(self) -> str | None:
        return app_settings.cache_redis_url

    @property
    def ttl_seconds(self) -> int:
        return app_settings.cache_ttl_seconds

    @property
    def key_prefix(self) -> str:
        return app_settings.cache_key_prefix


cache_settings = _CacheSettingsProxy()
