"""Benchmark utilities for AgenticAPI performance testing.

Provides a lightweight benchmark runner for measuring and asserting
performance targets in CI/CD pipelines.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Result of a benchmark run.

    Attributes:
        name: Name of the benchmark.
        iterations: Number of iterations run.
        total_ms: Total time in milliseconds.
        mean_ms: Mean time per iteration in milliseconds.
        min_ms: Minimum time in milliseconds.
        max_ms: Maximum time in milliseconds.
    """

    name: str
    iterations: int
    total_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float


class BenchmarkRunner:
    """Lightweight benchmark runner for performance measurement.

    Measures execution time of synchronous functions and stores
    results for subsequent assertion against targets.

    Example:
        runner = BenchmarkRunner()
        result = runner.run("intent_parse", fn=parser.parse, iterations=100)
        runner.assert_within_target("intent_parse", target_ms=50.0)
    """

    def __init__(self) -> None:
        """Initialize the benchmark runner."""
        self._results: dict[str, BenchmarkResult] = {}

    @property
    def results(self) -> dict[str, BenchmarkResult]:
        """All stored benchmark results."""
        return dict(self._results)

    def run(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        iterations: int = 100,
        warmup: int = 5,
    ) -> BenchmarkResult:
        """Run a synchronous benchmark.

        Args:
            name: Name for this benchmark.
            fn: The function to benchmark.
            args: Positional arguments for fn.
            kwargs: Keyword arguments for fn.
            iterations: Number of iterations to measure.
            warmup: Number of warmup iterations (not measured).

        Returns:
            BenchmarkResult with timing statistics.
        """
        kw = kwargs or {}

        # Warmup
        for _ in range(warmup):
            fn(*args, **kw)

        # Measure
        times_ms: list[float] = []
        total_start = time.perf_counter_ns()

        for _ in range(iterations):
            start = time.perf_counter_ns()
            fn(*args, **kw)
            elapsed_ns = time.perf_counter_ns() - start
            times_ms.append(elapsed_ns / 1_000_000)

        total_elapsed_ns = time.perf_counter_ns() - total_start
        total_ms = total_elapsed_ns / 1_000_000

        result = BenchmarkResult(
            name=name,
            iterations=iterations,
            total_ms=total_ms,
            mean_ms=sum(times_ms) / len(times_ms),
            min_ms=min(times_ms),
            max_ms=max(times_ms),
        )

        self._results[name] = result

        logger.info(
            "benchmark_complete",
            name=name,
            iterations=iterations,
            mean_ms=f"{result.mean_ms:.3f}",
            min_ms=f"{result.min_ms:.3f}",
            max_ms=f"{result.max_ms:.3f}",
        )

        return result

    def assert_within_target(self, name: str, *, target_ms: float) -> None:
        """Assert that a benchmark's mean time is within target.

        Args:
            name: The benchmark name to check.
            target_ms: Maximum allowed mean time in milliseconds.

        Raises:
            AssertionError: If the mean time exceeds the target.
            KeyError: If no result exists for the given name.
        """
        result = self._results.get(name)
        if result is None:
            raise KeyError(f"No benchmark result for '{name}'. Run the benchmark first.")

        assert result.mean_ms <= target_ms, (
            f"Benchmark '{name}' mean {result.mean_ms:.3f}ms exceeds target {target_ms:.1f}ms"
        )
