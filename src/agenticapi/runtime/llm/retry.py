"""Retry wrapper for LLM backend calls.

Provides ``RetryConfig`` and ``with_retry()`` — a lightweight async
retry loop with exponential backoff and jitter, designed for transient
LLM provider errors (rate-limit, timeout, 5xx).
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Configuration for LLM call retries.

    Attributes:
        max_retries: Maximum number of retry attempts (0 = no retries).
        base_delay_seconds: Initial delay before the first retry.
        max_delay_seconds: Upper bound on delay between retries.
        jitter: Whether to add random jitter to the delay.
        retryable_exceptions: Exception types that trigger a retry.
    """

    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = field(default_factory=tuple)


async def with_retry(
    fn: Any,
    retry_config: RetryConfig,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute *fn* with exponential-backoff retries on transient errors.

    Args:
        fn: An async callable to invoke.
        retry_config: Retry configuration.
        *args: Positional arguments forwarded to *fn*.
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The return value of *fn* on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(1 + retry_config.max_retries):
        try:
            return await fn(*args, **kwargs)  # type: ignore[no-any-return]
        except retry_config.retryable_exceptions as exc:
            last_exc = exc
            if attempt >= retry_config.max_retries:
                logger.warning(
                    "llm_retry_exhausted",
                    attempts=attempt + 1,
                    error=str(exc),
                )
                raise

            delay = min(
                retry_config.base_delay_seconds * (2**attempt),
                retry_config.max_delay_seconds,
            )
            if retry_config.jitter:
                delay *= 0.5 + random.random()

            logger.info(
                "llm_retry_attempt",
                attempt=attempt + 1,
                max_retries=retry_config.max_retries,
                delay=round(delay, 2),
                error=str(exc),
            )
            await asyncio.sleep(delay)

    # Should never reach here, but satisfy type checker.
    if last_exc is not None:
        raise last_exc
    msg = "with_retry: no attempts made"
    raise RuntimeError(msg)
