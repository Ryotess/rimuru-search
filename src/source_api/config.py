from src.config import app_settings


class _SourceApiSettingsProxy:
    """Proxy that exposes source API fields from the unified settings."""

    @property
    def base_url(self) -> str:
        return app_settings.source_api_base_url

    @property
    def documents_path(self) -> str:
        return app_settings.source_api_documents_path


source_api_settings = _SourceApiSettingsProxy()
