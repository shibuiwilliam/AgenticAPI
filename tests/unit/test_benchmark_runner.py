"""Tests for BenchmarkRunner."""

from __future__ import annotations

import pytest

from agenticapi.testing.benchmark import BenchmarkRunner


class TestBenchmarkRunner:
    def test_run_returns_result(self) -> None:
        runner = BenchmarkRunner()
        result = runner.run("test", fn=lambda: sum(range(100)), iterations=10)
        assert result.name == "test"
        assert result.iterations == 10
        assert result.mean_ms > 0
        assert result.min_ms > 0
        assert result.max_ms >= result.min_ms

    def test_results_stored(self) -> None:
        runner = BenchmarkRunner()
        runner.run("bench1", fn=lambda: None, iterations=5)
        assert "bench1" in runner.results

    def test_assert_within_target_passes(self) -> None:
        runner = BenchmarkRunner()
        runner.run("fast", fn=lambda: None, iterations=10)
        # Should be well under 100ms
        runner.assert_within_target("fast", target_ms=100.0)

    def test_assert_within_target_fails(self) -> None:
        runner = BenchmarkRunner()
        # Run something that should take >0ms
        runner.run("slow", fn=lambda: sum(range(100000)), iterations=10)
        # Extremely tight target should fail
        with pytest.raises(AssertionError, match="exceeds target"):
            runner.assert_within_target("slow", target_ms=0.0001)

    def test_assert_within_target_missing_raises(self) -> None:
        runner = BenchmarkRunner()
        with pytest.raises(KeyError, match="No benchmark result"):
            runner.assert_within_target("nonexistent", target_ms=10.0)

    def test_run_with_args(self) -> None:
        runner = BenchmarkRunner()
        result = runner.run(
            "add",
            fn=lambda a, b: a + b,
            args=(1, 2),
            iterations=5,
        )
        assert result.iterations == 5

    def test_run_with_kwargs(self) -> None:
        runner = BenchmarkRunner()

        def my_fn(x: int = 0) -> int:
            return x * 2

        result = runner.run("mul", fn=my_fn, kwargs={"x": 5}, iterations=5)
        assert result.iterations == 5

    def test_warmup_runs(self) -> None:
        call_count = 0

        def counting_fn() -> None:
            nonlocal call_count
            call_count += 1

        runner = BenchmarkRunner()
        runner.run("count", fn=counting_fn, iterations=10, warmup=3)
        assert call_count == 13  # 3 warmup + 10 measured
