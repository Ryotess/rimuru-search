# src/cache/client.py
from __future__ import annotations

from contextlib import suppress

import redis.asyncio as redis_asyncio
from loguru import logger

from src.cache.config import cache_settings

_client: redis_asyncio.Redis | None = None


def get_redis() -> redis_asyncio.Redis | None:
    """Return a module-singleton async Redis client, or None if not configured."""
    global _client
    if _client is not None:
        return _client
    if not cache_settings.redis_url:
        return None
    try:
        _client = redis_asyncio.Redis.from_url(
            cache_settings.redis_url, decode_responses=False
        )
        logger.info("Redis cache client initialized")
        return _client
    except Exception as exc:
        logger.warning("Redis client init failed ({}); cache disabled", exc)
        return None


async def close_redis() -> None:
    global _client
    if _client is not None:
        with suppress(Exception):
            await _client.aclose()
        _client = None
