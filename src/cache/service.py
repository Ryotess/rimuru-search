# src/cache/service.py
from __future__ import annotations

import hashlib
import json
from typing import Any, overload

from loguru import logger
from pydantic import BaseModel

from src.cache.config import cache_settings
from src.config import app_settings
from src.orchestrator.schemas import SearchRequest, SearchResponse

# Excluded from the key so bypass_cache=True doesn't shard the keyspace.
_NON_KEY_FIELDS: set[str] = {"bypass_cache"}


def build_cache_key(payload: SearchRequest, variant: str = "details") -> str:
    """Stable SHA256 of the SearchRequest (excluding non-key fields)."""
    subset = {
        "variant": variant,
        "lexical_backend": app_settings.search_lexical_backend,
        "request": payload.model_dump(exclude=_NON_KEY_FIELDS),
    }
    digest = hashlib.sha256(_stable_json(subset).encode("utf-8")).hexdigest()
    return f"{cache_settings.key_prefix}:{digest}"


def _stable_json(obj: Any) -> str:
    def _canonical(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: _canonical(o[k]) for k in sorted(o)}
        if isinstance(o, list) and all(isinstance(x, str) for x in o):
            return sorted(o)
        if isinstance(o, list):
            return [_canonical(x) for x in o]
        return o

    return json.dumps(_canonical(obj), ensure_ascii=False, separators=(",", ":"))


@overload
async def get_cached[ResponseModel: BaseModel](
    client,
    payload: SearchRequest,
    response_model: type[ResponseModel],
    variant: str = "details",
) -> ResponseModel | None: ...


@overload
async def get_cached(
    client,
    payload: SearchRequest,
    response_model: type[SearchResponse] = SearchResponse,
    variant: str = "details",
) -> SearchResponse | None: ...


async def get_cached(
    client,
    payload: SearchRequest,
    response_model: type[BaseModel] = SearchResponse,
    variant: str = "details",
) -> BaseModel | None:
    """Return cached SearchResponse or None. Fail-open on any Redis error."""
    if client is None:
        return None
    key = build_cache_key(payload, variant=variant)
    try:
        raw = await client.get(key)
    except Exception as exc:
        logger.warning("Cache get failed ({}); continuing without cache", exc)
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return response_model.model_validate_json(raw)
    except Exception as exc:
        logger.warning("Cache value deserialize failed ({}); treating as miss", exc)
        return None


async def set_cached(
    client,
    payload: SearchRequest,
    response: BaseModel,
    ttl_seconds: int | None = None,
    variant: str = "details",
) -> None:
    """Write response to cache with TTL. Fail-open on any Redis error."""
    if client is None:
        return
    key = build_cache_key(payload, variant=variant)
    ttl = ttl_seconds if ttl_seconds is not None else cache_settings.ttl_seconds
    try:
        await client.set(key, response.model_dump_json(), ex=ttl)
    except Exception as exc:
        logger.warning("Cache set failed ({}); continuing", exc)


async def invalidate_search_cache(client) -> int:
    """Delete search response keys while preserving coordination keys."""
    if client is None:
        return 0

    prefix = f"{cache_settings.key_prefix}:"
    keys_to_delete: list[bytes | str] = []
    try:
        async for key in client.scan_iter(match=f"{prefix}*"):
            key_text = key.decode("utf-8") if isinstance(key, bytes) else key
            suffix = key_text.removeprefix(prefix)
            if len(suffix) == 64 and all(char in "0123456789abcdef" for char in suffix):
                keys_to_delete.append(key)

        if keys_to_delete:
            await client.delete(*keys_to_delete)
        logger.info("Invalidated {} cached search responses", len(keys_to_delete))
        return len(keys_to_delete)
    except Exception as exc:
        logger.warning("Cache invalidation failed ({}); continuing", exc)
        return 0
