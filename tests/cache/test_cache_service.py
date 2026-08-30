"""Tests for src/cache/service.py — the Redis-backed search-response cache."""

from __future__ import annotations

from unittest.mock import patch

import fakeredis.aioredis
import pytest

from src.cache.service import (
    build_cache_key,
    get_cached,
    invalidate_search_cache,
    set_cached,
)
from src.orchestrator.schemas import RerankedHit, SearchRequest, SearchResponse


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def sample_request() -> SearchRequest:
    return SearchRequest(query="steel")


@pytest.fixture
def sample_response(sample_request: SearchRequest) -> SearchResponse:
    return SearchResponse(
        query=sample_request.query,
        hits=[
            RerankedHit(
                id="document-a",
                content="A searchable document",
                rrf_score=0.1,
                rerank_score=0.9,
            )
        ],
    )


@pytest.mark.asyncio
async def test_cache_miss_returns_none(fake_redis, sample_request):
    got = await get_cached(fake_redis, sample_request)
    assert got is None


@pytest.mark.asyncio
async def test_set_then_get_returns_cached_response(
    fake_redis, sample_request, sample_response
):
    await set_cached(fake_redis, sample_request, sample_response, ttl_seconds=60)
    got = await get_cached(fake_redis, sample_request)
    assert got is not None
    assert got.model_dump() == sample_response.model_dump()


@pytest.mark.asyncio
async def test_set_cached_applies_ttl(fake_redis, sample_request, sample_response):
    await set_cached(fake_redis, sample_request, sample_response, ttl_seconds=42)
    key = build_cache_key(sample_request)
    ttl = await fake_redis.ttl(key)
    assert 0 < ttl <= 42


@pytest.mark.asyncio
async def test_none_client_is_fail_open(sample_request, sample_response):
    """When redis client is None (unconfigured), get returns None and set no-ops."""
    assert await get_cached(None, sample_request) is None
    await set_cached(None, sample_request, sample_response, ttl_seconds=60)


@pytest.mark.asyncio
async def test_redis_exception_is_fail_open(sample_request, sample_response):
    """If Redis raises on get/set, we log and return None / noop instead of propagating."""

    class BoomRedis:
        async def get(self, _key):
            raise RuntimeError("connection refused")

        async def set(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    client = BoomRedis()
    assert await get_cached(client, sample_request) is None
    # must not raise
    await set_cached(client, sample_request, sample_response, ttl_seconds=60)


def test_build_cache_key_is_stable_across_equivalent_requests():
    req_a = SearchRequest(query="steel")
    req_b = SearchRequest(query="steel")
    assert build_cache_key(req_a) == build_cache_key(req_b)


def test_build_cache_key_differs_for_different_inputs():
    base = SearchRequest(query="steel")
    variants = [
        SearchRequest(query="aluminum"),
        SearchRequest(query="steel", rerank_top_n=5),
        SearchRequest(query="steel", use_fuzzy=True),
    ]
    base_key = build_cache_key(base)
    for v in variants:
        assert build_cache_key(v) != base_key, f"key collision for variant: {v}"


def test_build_cache_key_separates_lexical_backends():
    request = SearchRequest(query="steel")
    with patch("src.cache.service.app_settings.search_lexical_backend", "bm25"):
        bm25_key = build_cache_key(request)
    with patch("src.cache.service.app_settings.search_lexical_backend", "fts"):
        fts_key = build_cache_key(request)

    assert bm25_key != fts_key


def test_build_cache_key_ignores_bypass_flag():
    """bypass_cache must NOT affect the key — otherwise bypass=True would never warm up cache."""
    a = SearchRequest(query="steel")
    b = SearchRequest(query="steel", bypass_cache=True)
    assert build_cache_key(a) == build_cache_key(b)


def test_cache_key_separates_full_and_ids_responses():
    request = SearchRequest(query="steel")
    assert build_cache_key(request) != build_cache_key(request, variant="ids")


@pytest.mark.asyncio
async def test_invalidate_search_cache_preserves_seeding_lock(
    fake_redis, sample_request, sample_response
):
    await set_cached(fake_redis, sample_request, sample_response, ttl_seconds=60)
    search_key = build_cache_key(sample_request)
    lock_key = "hybrid-search:search:v2:seeding:lock"
    await fake_redis.set(lock_key, "task-id")

    deleted = await invalidate_search_cache(fake_redis)

    assert deleted == 1
    assert await fake_redis.get(search_key) is None
    assert await fake_redis.get(lock_key) == b"task-id"


@pytest.mark.asyncio
async def test_invalidate_search_cache_is_fail_open():
    class BoomRedis:
        def scan_iter(self, **kwargs):
            raise RuntimeError("connection refused")

    assert await invalidate_search_cache(BoomRedis()) == 0
