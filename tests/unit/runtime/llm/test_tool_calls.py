"""Unit tests for ``LLMResponse.tool_calls`` and ``MockBackend`` (Phase E3).

Verifies the new ``ToolCall`` dataclass, the ``tool_calls`` field on
``LLMResponse``, ``finish_reason``, and the ``MockBackend`` queue
semantics for ``add_tool_call_response``.
"""

from __future__ import annotations

import pytest

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm import (
    LLMMessage,
    LLMPrompt,
    LLMResponse,
    MockBackend,
    ToolCall,
)


def _prompt_with_tools() -> LLMPrompt:
    return LLMPrompt(
        system="You are an assistant.",
        messages=[LLMMessage(role="user", content="Look up user 42")],
        tools=[
            {
                "name": "get_user",
                "description": "Look up a user by id",
                "parameters": {
                    "type": "object",
                    "properties": {"user_id": {"type": "integer"}},
                    "required": ["user_id"],
                },
            }
        ],
    )


class TestToolCallDataclass:
    def test_construct_and_fields(self) -> None:
        call = ToolCall(id="call_1", name="get_user", arguments={"user_id": 42})
        assert call.id == "call_1"
        assert call.name == "get_user"
        assert call.arguments == {"user_id": 42}

    def test_immutable(self) -> None:
        call = ToolCall(id="x", name="y", arguments={})
        with pytest.raises((AttributeError, TypeError)):
            call.id = "z"  # type: ignore[misc]


class TestLLMResponseToolCalls:
    def test_default_tool_calls_empty(self) -> None:
        resp = LLMResponse(content="hello")
        assert resp.tool_calls == []
        assert resp.finish_reason is None

    def test_response_with_tool_calls(self) -> None:
        calls = [ToolCall(id="c1", name="get_user", arguments={"id": 1})]
        resp = LLMResponse(content="", tool_calls=calls, finish_reason="tool_calls")
        assert resp.tool_calls == calls
        assert resp.finish_reason == "tool_calls"


class TestMockBackendToolCallPath:
    async def test_tool_call_response_returned_when_tools_present(self) -> None:
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="get_user", arguments={"user_id": 42}))

        response = await backend.generate(_prompt_with_tools())
        assert response.content == ""
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_user"
        assert response.tool_calls[0].arguments == {"user_id": 42}
        assert response.finish_reason == "tool_calls"

    async def test_batched_tool_calls(self) -> None:
        backend = MockBackend()
        backend.add_tool_call_response(
            [
                ToolCall(id="c1", name="get_user", arguments={"user_id": 1}),
                ToolCall(id="c2", name="get_orders", arguments={"user_id": 1}),
            ]
        )
        response = await backend.generate(_prompt_with_tools())
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0].name == "get_user"
        assert response.tool_calls[1].name == "get_orders"

    async def test_falls_through_to_text_when_no_tool_call_queued(self) -> None:
        """If tools are present but no tool_call_response queued, fall back to text."""
        backend = MockBackend(responses=["plain text answer"])
        response = await backend.generate(_prompt_with_tools())
        assert response.content == "plain text answer"
        assert response.tool_calls == []

    async def test_text_path_unaffected_when_tools_absent(self) -> None:
        backend = MockBackend(responses=["hello"])
        prompt = LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")])
        response = await backend.generate(prompt)
        assert response.content == "hello"
        assert response.tool_calls == []

    async def test_text_path_raises_when_no_responses(self) -> None:
        backend = MockBackend()
        prompt = LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")])
        with pytest.raises(CodeGenerationError):
            await backend.generate(prompt)

    async def test_call_count_includes_tool_call_responses(self) -> None:
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="t", arguments={}))
        await backend.generate(_prompt_with_tools())
        assert backend.call_count == 1

    async def test_priority_tool_calls_over_response_schema(self) -> None:
        """Tool call branch beats schema branch when both apply."""
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="t", arguments={"x": 1}))
        backend.add_structured_response({"foo": "bar"})

        prompt = LLMPrompt(
            system="x",
            messages=[LLMMessage(role="user", content="x")],
            tools=[{"name": "t", "description": "t", "parameters": {}}],
            response_schema={"type": "object"},
            response_schema_name="X",
        )
        response = await backend.generate(prompt)
        # Tool call wins.
        assert response.tool_calls and response.tool_calls[0].name == "t"
        # The structured response queue is untouched.
        assert backend._structured_responses == [{"foo": "bar"}]
