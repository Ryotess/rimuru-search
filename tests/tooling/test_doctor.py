import io
from unittest.mock import MagicMock, patch

from scripts.doctor import _model_check, deprecated_setting_names, redact_url


def test_redact_url_hides_database_password():
    value = redact_url("postgresql://search:secret@localhost:5432/search")
    assert value == "postgresql://search:***@localhost:5432/search"
    assert "secret" not in value


def test_redact_url_leaves_url_without_password_unchanged():
    assert redact_url("http://localhost:8000") == "http://localhost:8000"


def test_model_check_reports_served_name_mismatch():
    response = MagicMock()
    response.__enter__.return_value = io.StringIO('{"data":[{"id":"actual-model"}]}')
    response.__exit__.return_value = None

    with patch("scripts.doctor.urllib.request.urlopen", return_value=response):
        result = _model_check(
            "Embedding service",
            "http://localhost:5678/v1",
            "hosted_vllm/configured-model",
        )

    assert result.ok is False
    assert "configured-model" in result.detail


def test_deprecated_setting_names_detects_environment_name(monkeypatch):
    monkeypatch.setenv("EMBED_EMBEDDING_MODEL", "value-is-never-returned")

    assert "EMBED_EMBEDDING_MODEL" in deprecated_setting_names()
