"""Retry utilities for transient LLM / network errors in the seeding pipeline."""

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx
import litellm

RETRYABLE_EXCEPTIONS = (
    litellm.Timeout,
    litellm.InternalServerError,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)


def is_retryable(exc: Exception) -> bool:
    return isinstance(exc, RETRYABLE_EXCEPTIONS)


async def retry_with_backoff[ResultT](
    fn: Callable[[], Awaitable[ResultT]],
    *,
    max_retries: int = 3,
    base_delay: float = 2.0,
    jitter_fraction: float = 0.25,
) -> ResultT:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                jitter = delay * jitter_fraction * (2 * random.random() - 1)  # noqa: S311  # Retry jitter is not security-sensitive.
                await asyncio.sleep(delay + jitter)
    if last_exc is None:
        raise RuntimeError("retry loop ended without a result or exception")
    raise last_exc
