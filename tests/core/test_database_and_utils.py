import numpy as np
import pytest

from src.database import _as_async_url
from src.lexical_search.utils import normalize_query
from src.models import Document
from src.orchestrator.exceptions import EmbeddingParseException
from src.orchestrator.utils import extract_embedding_vector
from src.vector_search.utils import to_float32


def test_as_async_url_upgrades_sync_prefix():
    """A plain PostgreSQL URL uses the async-compatible psycopg driver."""
    url = _as_async_url("postgresql://user:pass@db:5432/app")
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "db"
    assert url.port == 5432
    assert url.database == "app"


def test_document_identity_is_scoped_by_collection():
    assert [column.name for column in Document.__table__.primary_key] == [
        "collection",
        "id",
    ]


def test_as_async_url_normalizes_driver_and_other_urls():
    """PostgreSQL drivers are normalized while unrelated URLs remain intact."""
    url1 = _as_async_url("postgresql+asyncpg://db.example/app")
    assert url1.drivername == "postgresql+psycopg"

    url2 = _as_async_url("postgresql+psycopg://db.example/app")
    assert url2.drivername == "postgresql+psycopg"

    url3 = _as_async_url("sqlite:///local.db")
    assert url3.drivername == "sqlite"


def test_to_float32_converts_and_preserves_values():
    vec = [1, 2.5, -3.25]
    arr = to_float32(vec)
    assert isinstance(arr, np.ndarray)
    assert arr.dtype == np.float32
    np.testing.assert_allclose(arr, np.array(vec, dtype=np.float32))


def test_normalize_query_strips_whitespace_and_none():
    assert normalize_query("  hello  ") == "hello"
    assert normalize_query(None) == ""


def test_extract_embedding_vector_happy_path():
    mock_response = type(
        "Resp",
        (),
        {"data": [{"embedding": [0.1, 0.2, 0.3]}]},
    )()

    vector = extract_embedding_vector(mock_response)
    assert vector == [0.1, 0.2, 0.3]


def test_extract_embedding_vector_raises_on_missing_data():
    empty_resp = type("Resp", (), {"data": []})()
    with pytest.raises(EmbeddingParseException):
        extract_embedding_vector(empty_resp)

    missing_embedding = type("Resp", (), {"data": [{}]})()
    with pytest.raises(EmbeddingParseException):
        extract_embedding_vector(missing_embedding)

    not_iterable = type("Resp", (), {"data": [{"embedding": 123}]})()
    with pytest.raises(EmbeddingParseException):
        extract_embedding_vector(not_iterable)
