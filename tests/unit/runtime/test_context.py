"""Tests for AgentContext and ContextWindow."""

from __future__ import annotations

from agenticapi.runtime.context import AgentContext, ContextItem, ContextWindow


class TestContextItem:
    def test_creation(self) -> None:
        item = ContextItem(key="schema", value="CREATE TABLE orders ...", source="tool")
        assert item.key == "schema"
        assert item.source == "tool"
        assert item.priority == 0

    def test_priority(self) -> None:
        item = ContextItem(key="important", value="data", source="user", priority=10)
        assert item.priority == 10

    def test_frozen(self) -> None:
        item = ContextItem(key="k", value="v", source="s")
        # frozen=True means we can't change attributes
        import pytest

        with pytest.raises(AttributeError):
            item.key = "changed"  # type: ignore[misc]


class TestContextWindow:
    def test_add_and_build(self) -> None:
        window = ContextWindow()
        window.add(ContextItem(key="info", value="some data", source="test"))
        built = window.build()
        assert "info" in built
        assert "some data" in built

    def test_build_empty(self) -> None:
        window = ContextWindow()
        assert window.build() == ""

    def test_estimated_tokens_empty(self) -> None:
        window = ContextWindow()
        assert window.estimated_tokens() == 0

    def test_estimated_tokens_positive(self) -> None:
        window = ContextWindow()
        window.add(ContextItem(key="data", value="x" * 100, source="test"))
        assert window.estimated_tokens() > 0

    def test_priority_ordering(self) -> None:
        window = ContextWindow()
        window.add(ContextItem(key="low", value="low priority", source="test", priority=1))
        window.add(ContextItem(key="high", value="high priority", source="test", priority=10))
        built = window.build()
        # High priority should appear before low priority
        high_pos = built.index("high priority")
        low_pos = built.index("low priority")
        assert high_pos < low_pos

    def test_respects_max_tokens(self) -> None:
        window = ContextWindow(max_tokens=1)  # Very small budget
        window.add(ContextItem(key="data", value="x" * 1000, source="test"))
        # The item should be silently dropped
        assert len(window.items) == 0

    def test_multiple_items(self) -> None:
        window = ContextWindow()
        window.add(ContextItem(key="a", value="alpha", source="s1"))
        window.add(ContextItem(key="b", value="beta", source="s2"))
        built = window.build()
        assert "alpha" in built
        assert "beta" in built

    def test_clear(self) -> None:
        window = ContextWindow()
        window.add(ContextItem(key="x", value="y", source="z"))
        assert len(window.items) == 1
        window.clear()
        assert len(window.items) == 0


class TestAgentContext:
    def test_creation(self) -> None:
        ctx = AgentContext(trace_id="trace-1", endpoint_name="orders")
        assert ctx.trace_id == "trace-1"
        assert ctx.endpoint_name == "orders"
        assert ctx.session_id is None
        assert ctx.user_id is None
        assert ctx.metadata == {}

    def test_with_session(self) -> None:
        ctx = AgentContext(trace_id="t", endpoint_name="e", session_id="s123")
        assert ctx.session_id == "s123"

    def test_context_window_default(self) -> None:
        ctx = AgentContext(trace_id="t", endpoint_name="e")
        assert isinstance(ctx.context_window, ContextWindow)
        assert ctx.context_window.build() == ""

    def test_context_window_usable(self) -> None:
        ctx = AgentContext(trace_id="t", endpoint_name="e")
        ctx.context_window.add(ContextItem(key="k", value="v", source="s"))
        assert "v" in ctx.context_window.build()
