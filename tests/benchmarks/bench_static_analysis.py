"""Benchmark: Static analysis (AST check) performance.

Target: < 50ms per 1000 lines of code.
"""

from __future__ import annotations

import pytest

from agenticapi.harness.sandbox.static_analysis import check_code_safety


def _generate_code(lines: int) -> str:
    """Generate sample code of the given line count."""
    parts = []
    for i in range(lines):
        parts.append(f"x_{i} = {i} * 2 + 1")
    return "\n".join(parts)


SMALL_CODE = _generate_code(100)
MEDIUM_CODE = _generate_code(500)
LARGE_CODE = _generate_code(1000)


@pytest.mark.benchmark
def test_bench_static_analysis_100_lines(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark static analysis on 100 lines of code."""

    def analyze() -> None:
        check_code_safety(
            SMALL_CODE,
            denied_modules=["os", "subprocess", "shutil"],
            deny_eval_exec=True,
            deny_dynamic_import=True,
        )

    benchmark(analyze)
    assert benchmark.stats["mean"] < 0.050  # 50ms


@pytest.mark.benchmark
def test_bench_static_analysis_500_lines(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark static analysis on 500 lines of code."""

    def analyze() -> None:
        check_code_safety(
            MEDIUM_CODE,
            denied_modules=["os", "subprocess", "shutil"],
            deny_eval_exec=True,
            deny_dynamic_import=True,
        )

    benchmark(analyze)
    assert benchmark.stats["mean"] < 0.050


@pytest.mark.benchmark
def test_bench_static_analysis_1000_lines(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark static analysis on 1000 lines of code."""

    def analyze() -> None:
        check_code_safety(
            LARGE_CODE,
            denied_modules=["os", "subprocess", "shutil"],
            deny_eval_exec=True,
            deny_dynamic_import=True,
        )

    benchmark(analyze)
    assert benchmark.stats["mean"] < 0.050  # 50ms for 1000 lines
