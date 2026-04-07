"""Benchmark: IntentParser performance.

Target: < 50ms mean per parse (without LLM).
"""

from __future__ import annotations

import pytest

from agenticapi.interface.intent import IntentParser


@pytest.mark.benchmark
def test_bench_intent_parsing_short(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark parsing a short intent."""
    parser = IntentParser()

    def parse_intent() -> None:
        parser._parse_with_keywords("show orders", {})

    benchmark(parse_intent)
    assert benchmark.stats["mean"] < 0.050  # 50ms


@pytest.mark.benchmark
def test_bench_intent_parsing_medium(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark parsing a medium-length intent."""
    parser = IntentParser()

    def parse_intent() -> None:
        parser._parse_with_keywords(
            "show me the top 10 products by revenue excluding out of stock items from last month",
            {},
        )

    benchmark(parse_intent)
    assert benchmark.stats["mean"] < 0.050


@pytest.mark.benchmark
def test_bench_intent_parsing_japanese(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark parsing a Japanese intent."""
    parser = IntentParser()

    def parse_intent() -> None:
        parser._parse_with_keywords("今月の注文数を教えて", {})

    benchmark(parse_intent)
    assert benchmark.stats["mean"] < 0.050


@pytest.mark.benchmark
def test_bench_intent_parsing_write(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark parsing a write intent."""
    parser = IntentParser()

    def parse_intent() -> None:
        parser._parse_with_keywords("delete all cancelled orders from the database", {})

    benchmark(parse_intent)
    assert benchmark.stats["mean"] < 0.050
