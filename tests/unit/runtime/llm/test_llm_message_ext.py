"""Unit tests for LLMMessage extended fields (tool_call_id, tool_calls)."""

from __future__ import annotations

from agenticapi.runtime.llm.base import LLMMessage, ToolCall


class TestLLMMessageExtensions:
    """Verify backward-compatible extension of LLMMessage."""

    def test_default_fields_are_none(self) -> None:
        msg = LLMMessage(role="user", content="hello")
        assert msg.tool_call_id is None
        assert msg.tool_calls is None

    def test_tool_call_id_on_tool_message(self) -> None:
        msg = LLMMessage(role="tool", content="result", tool_call_id="tc_1")
        assert msg.tool_call_id == "tc_1"
        assert msg.role == "tool"

    def test_tool_calls_on_assistant_message(self) -> None:
        calls = [ToolCall(id="c1", name="search", arguments={"q": "hi"})]
        msg = LLMMessage(role="assistant", content="", tool_calls=calls)
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"

    def test_frozen_constraint(self) -> None:
        msg = LLMMessage(role="user", content="hi")
        try:
            msg.content = "bye"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass

    def test_frozen_with_new_fields(self) -> None:
        msg = LLMMessage(role="tool", content="x", tool_call_id="id1")
        try:
            msg.tool_call_id = "id2"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass

    def test_backward_compat_positional(self) -> None:
        """Existing code creating LLMMessage(role, content) still works."""
        msg = LLMMessage("user", "hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_call_id is None
        assert msg.tool_calls is None
