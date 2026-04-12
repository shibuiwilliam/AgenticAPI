"""Unit tests for ``RetryConfig`` and ``with_retry()``."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agenticapi.runtime.llm.retry import RetryConfig, with_retry


class TestRetryConfig:
    def test_defaults(self) -> None:
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay_seconds == 1.0
        assert cfg.max_delay_seconds == 30.0
        assert cfg.jitter is True
        assert cfg.retryable_exceptions == ()

    def test_immutable(self) -> None:
        cfg = RetryConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.max_retries = 5  # type: ignore[misc]


class TestWithRetry:
    async def test_success_on_first_attempt(self) -> None:
        fn = AsyncMock(return_value="ok")
        cfg = RetryConfig(retryable_exceptions=(ValueError,))
        result = await with_retry(fn, cfg)
        assert result == "ok"
        assert fn.call_count == 1

    @patch("agenticapi.runtime.llm.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_retryable_error(self, mock_sleep: AsyncMock) -> None:
        fn = AsyncMock(side_effect=[ValueError("rate limit"), ValueError("rate limit"), "ok"])
        cfg = RetryConfig(max_retries=3, retryable_exceptions=(ValueError,), jitter=False)
        result = await with_retry(fn, cfg)
        assert result == "ok"
        assert fn.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("agenticapi.runtime.llm.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_exponential_backoff(self, mock_sleep: AsyncMock) -> None:
        fn = AsyncMock(side_effect=[ValueError("err"), ValueError("err"), "ok"])
        cfg = RetryConfig(max_retries=3, base_delay_seconds=1.0, jitter=False, retryable_exceptions=(ValueError,))
        await with_retry(fn, cfg)
        # attempt 0 fails -> delay 1*2^0=1.0, attempt 1 fails -> delay 1*2^1=2.0
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0]

    @patch("agenticapi.runtime.llm.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_max_delay_cap(self, mock_sleep: AsyncMock) -> None:
        fn = AsyncMock(side_effect=[ValueError("err"), ValueError("err"), "ok"])
        cfg = RetryConfig(
            max_retries=3,
            base_delay_seconds=20.0,
            max_delay_seconds=5.0,
            jitter=False,
            retryable_exceptions=(ValueError,),
        )
        await with_retry(fn, cfg)
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert all(d <= 5.0 for d in delays)

    async def test_raises_non_retryable_immediately(self) -> None:
        fn = AsyncMock(side_effect=TypeError("bad"))
        cfg = RetryConfig(retryable_exceptions=(ValueError,))
        with pytest.raises(TypeError, match="bad"):
            await with_retry(fn, cfg)
        assert fn.call_count == 1

    @patch("agenticapi.runtime.llm.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_exhausted_retries_raises_last_error(self, mock_sleep: AsyncMock) -> None:
        fn = AsyncMock(side_effect=ValueError("rate limit"))
        cfg = RetryConfig(max_retries=2, retryable_exceptions=(ValueError,), jitter=False)
        with pytest.raises(ValueError, match="rate limit"):
            await with_retry(fn, cfg)
        assert fn.call_count == 3  # 1 initial + 2 retries

    @patch("agenticapi.runtime.llm.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_jitter_varies_delay(self, mock_sleep: AsyncMock) -> None:
        fn = AsyncMock(side_effect=[ValueError("err"), "ok"])
        cfg = RetryConfig(max_retries=2, base_delay_seconds=1.0, jitter=True, retryable_exceptions=(ValueError,))
        await with_retry(fn, cfg)
        delay = mock_sleep.call_args_list[0].args[0]
        # With jitter: delay = base * (0.5 + rand) where rand in [0,1)
        # So delay in [0.5, 1.5)
        assert 0.4 <= delay <= 1.6

    async def test_zero_retries_raises_immediately(self) -> None:
        fn = AsyncMock(side_effect=ValueError("err"))
        cfg = RetryConfig(max_retries=0, retryable_exceptions=(ValueError,))
        with pytest.raises(ValueError, match="err"):
            await with_retry(fn, cfg)
        assert fn.call_count == 1
