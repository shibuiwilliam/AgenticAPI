"""Tests for HarnessDepends dependency injection marker."""

from __future__ import annotations

from agenticapi.params import HarnessDepends


def _dummy_provider() -> str:
    return "harness-value"


class TestHarnessDepends:
    def test_stores_dependency(self) -> None:
        dep = HarnessDepends(_dummy_provider)
        assert dep.dependency is _dummy_provider

    def test_repr(self) -> None:
        dep = HarnessDepends(_dummy_provider)
        r = repr(dep)
        assert "HarnessDepends" in r
        assert "_dummy_provider" in r

    def test_callable_dependency(self) -> None:
        dep = HarnessDepends(lambda: 42)
        assert dep.dependency() == 42
