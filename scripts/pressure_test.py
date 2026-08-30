#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class LoadResult:
    success: int = 0
    failed: int = 0
    response_times: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def percentile(values: list[float], percentile_value: float) -> float:
    """Return a nearest-rank percentile for a non-empty sample."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value * len(ordered)))
    return ordered[rank - 1]


class LoadTest:
    def __init__(
        self,
        base_url: str,
        concurrency: int,
        collection: str,
        bypass_cache: bool,
    ) -> None:
        self.endpoint = f"{base_url.rstrip('/')}/v1/search"
        self.concurrency = concurrency
        self.collection = collection
        self.bypass_cache = bypass_cache

    def payload(self, query: str) -> dict:
        return {
            "query": query,
            "collection": self.collection,
            "bypass_cache": self.bypass_cache,
        }

    async def send_request(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        query: str,
    ) -> tuple[bool, float, str | None]:
        started = time.perf_counter()
        try:
            async with semaphore:
                response = await client.post(self.endpoint, json=self.payload(query))
            elapsed = time.perf_counter() - started
            if not response.is_success:
                return (
                    False,
                    elapsed,
                    f"HTTP {response.status_code}: {response.text[:200]}",
                )
            response.json()
            return True, elapsed, None
        except Exception as exc:
            return False, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"

    async def warm(self, queries: list[str]) -> None:
        limits = httpx.Limits(max_connections=min(self.concurrency, len(queries)))
        async with httpx.AsyncClient(timeout=30, limits=limits) as client:
            for query in dict.fromkeys(queries):
                response = await client.post(self.endpoint, json=self.payload(query))
                response.raise_for_status()

    async def run(self, request_count: int, queries: list[str]) -> LoadResult:
        result = LoadResult()
        semaphore = asyncio.Semaphore(self.concurrency)
        limits = httpx.Limits(
            max_connections=self.concurrency,
            max_keepalive_connections=self.concurrency,
        )
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            requests = [
                self.send_request(client, semaphore, queries[index % len(queries)])
                for index in range(request_count)
            ]
            for success, elapsed, error in await asyncio.gather(*requests):
                if success:
                    result.success += 1
                    result.response_times.append(elapsed)
                else:
                    result.failed += 1
                    if error:
                        result.errors.append(error)
        return result


def print_statistics(result: LoadResult, duration: float) -> None:
    total = result.success + result.failed
    print(f"requests={total} success={result.success} failed={result.failed}")
    print(f"duration_seconds={duration:.3f} throughput_rps={total / duration:.2f}")
    if result.response_times:
        values = result.response_times
        print(
            "latency_ms "
            f"mean={statistics.mean(values) * 1000:.2f} "
            f"p50={percentile(values, 0.50) * 1000:.2f} "
            f"p95={percentile(values, 0.95) * 1000:.2f} "
            f"p99={percentile(values, 0.99) * 1000:.2f} "
            f"max={max(values) * 1000:.2f}"
        )
    for error in result.errors[:5]:
        print(f"error={error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a small, configurable API load smoke test. Use a dedicated load "
            "tool and environment for capacity certification."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--collection", default="default")
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Repeat to distribute requests across multiple queries.",
    )
    parser.add_argument("--warm-cache", action="store_true")
    parser.add_argument("--bypass-cache", action="store_true")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")
    return args


async def main() -> None:
    args = parse_args()
    queries = args.queries or ["hybrid search"]
    test = LoadTest(
        base_url=args.base_url,
        concurrency=args.concurrency,
        collection=args.collection,
        bypass_cache=args.bypass_cache,
    )
    if args.warm_cache:
        await test.warm(queries)

    started = time.perf_counter()
    result = await test.run(args.requests, queries)
    print_statistics(result, time.perf_counter() - started)
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
