import pytest

from src.embedding.exceptions import EmbeddingException
from src.embedding.service.embed_query import encode_query


@pytest.mark.asyncio
async def test_encode_query_returns_embedding(monkeypatch):
    calls = {}

    async def fake_aembedding(model, input, api_base):
        calls["args"] = (model, tuple(input), api_base)
        return {"data": [{"embedding": [1.0, 2.0]}]}

    monkeypatch.setattr("src.embedding.service.embed_query.aembedding", fake_aembedding)

    resp = await encode_query("hello")

    assert resp["data"][0]["embedding"] == [1.0, 2.0]
    assert calls["args"][1] == ("hello",)


@pytest.mark.asyncio
async def test_encode_query_raises_embedding_exception(monkeypatch):
    async def bad_aembedding(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("src.embedding.service.embed_query.aembedding", bad_aembedding)

    with pytest.raises(EmbeddingException):
        await encode_query("fail")
