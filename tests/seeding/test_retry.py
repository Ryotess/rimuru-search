"""Tests for src.seeding.service.retry — retryable error classification and retry loop."""

import time

import httpx
import litellm
import pytest

from src.seeding.service.retry import is_retryable, retry_with_backoff


class TestIsRetryable:
    def test_litellm_timeout_is_retryable(self):
        exc = litellm.Timeout(message="timed out", model="test", llm_provider="vllm")
        assert is_retryable(exc) is True

    def test_litellm_internal_server_error_is_retryable(self):
        exc = litellm.InternalServerError(
            message="500", model="test", llm_provider="vllm"
        )
        assert is_retryable(exc) is True

    def test_httpx_connect_error_is_retryable(self):
        exc = httpx.ConnectError("connection refused")
        assert is_retryable(exc) is True

    def test_httpx_remote_protocol_error_is_retryable(self):
        exc = httpx.RemoteProtocolError("protocol error")
        assert is_retryable(exc) is True

    def test_httpx_read_error_is_retryable(self):
        exc = httpx.ReadError("read error")
        assert is_retryable(exc) is True

    def test_value_error_is_not_retryable(self):
        assert is_retryable(ValueError("bad value")) is False

    def test_runtime_error_is_not_retryable(self):
        assert is_retryable(RuntimeError("something broke")) is False

    def test_generic_exception_is_not_retryable(self):
        assert is_retryable(Exception("generic")) is False


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self):
        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error_then_succeeds(self):
        attempts = 0

        async def fn():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise litellm.Timeout(
                    message="timed out", model="test", llm_provider="vllm"
                )
            return "recovered"

        result = await retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result == "recovered"
        assert attempts == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries_exhausted(self):
        attempts = 0

        async def fn():
            nonlocal attempts
            attempts += 1
            raise litellm.Timeout(
                message="timed out", model="test", llm_provider="vllm"
            )

        with pytest.raises(litellm.Timeout):
            await retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert attempts == 4  # 1 initial + 3 retries

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        attempts = 0

        async def fn():
            nonlocal attempts
            attempts += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert attempts == 1

    @pytest.mark.asyncio
    async def test_backoff_increases_with_jitter(self):
        timestamps = []

        async def fn():
            timestamps.append(time.monotonic())
            if len(timestamps) < 4:
                raise litellm.Timeout(
                    message="timed out", model="test", llm_provider="vllm"
                )
            return "ok"

        await retry_with_backoff(
            fn, max_retries=3, base_delay=0.05, jitter_fraction=0.1
        )
        assert len(timestamps) == 4

        delay_1 = timestamps[1] - timestamps[0]
        delay_2 = timestamps[2] - timestamps[1]
        delay_3 = timestamps[3] - timestamps[2]

        # Each delay should roughly double (with jitter tolerance)
        assert delay_1 < delay_2
        assert delay_2 < delay_3

    @pytest.mark.asyncio
    async def test_httpx_connect_error_is_retried(self):
        attempts = 0

        async def fn():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("refused")
            return "ok"

        result = await retry_with_backoff(fn, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert attempts == 2
