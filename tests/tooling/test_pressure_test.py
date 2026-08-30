import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx

from scripts.pressure_test import LoadTest, percentile


def test_percentile_uses_nearest_rank():
    assert percentile([0.4, 0.1, 0.3, 0.2], 0.50) == 0.2
    assert percentile([0.4, 0.1, 0.3, 0.2], 0.95) == 0.4


async def test_send_request_treats_http_error_as_failure():
    response = MagicMock(spec=httpx.Response)
    response.is_success = False
    response.status_code = 502
    response.text = "model unavailable"
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    test = LoadTest(
        base_url="http://api",
        concurrency=1,
        collection="documents",
        bypass_cache=False,
    )

    success, _, error = await test.send_request(
        client,
        asyncio.Semaphore(1),
        "query",
    )

    assert success is False
    assert error == "HTTP 502: model unavailable"
