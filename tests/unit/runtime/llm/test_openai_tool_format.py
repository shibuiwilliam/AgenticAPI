"""Unit tests for OpenAIBackend tool format translation.

Verifies that:
- Tool definitions are wrapped in ``{"type": "function", "function": {...}}``.
- Multi-turn conversations with tool_calls and tool_call_id are
  correctly converted to OpenAI's ``tool_calls`` / ``tool_call_id`` format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt, ToolCall
from agenticapi.runtime.llm.retry import RetryConfig

# ---------------------------------------------------------------------------
# Fake OpenAI SDK types
# ---------------------------------------------------------------------------


@dataclass
class _Function:
    name: str = ""
    arguments: str = "{}"


@dataclass
class _ToolCallObj:
    id: str = ""
    type: str = "function"
    function: _Function = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.function is None:
            self.function = _Function()


@dataclass
class _Message:
    content: str | None = "ok"
    tool_calls: list[_ToolCallObj] | None = None


@dataclass
class _Choice:
    message: _Message = None  # type: ignore[assignment]
    finish_reason: str = "stop"

    def __post_init__(self) -> None:
        if self.message is None:
            self.message = _Message()


@dataclass
class _Usage:
    prompt_tokens: int = 10
    completion_tokens: int = 20


@dataclass
class _Completion:
    choices: list[_Choice] = None  # type: ignore[assignment]
    model: str = "gpt-5.4-mini"
    usage: _Usage = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.choices is None:
            self.choices = [_Choice()]
        if self.usage is None:
            self.usage = _Usage()


def _make_backend(client_mock: MagicMock) -> Any:
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        from agenticapi.runtime.llm.openai import OpenAIBackend

        backend = OpenAIBackend(retry=RetryConfig(max_retries=0, retryable_exceptions=()))
        backend._client = client_mock
        return backend


# ---------------------------------------------------------------------------
# Tool definition format tests
# ---------------------------------------------------------------------------


class TestOpenAIToolDefinitionFormat:
    """Verify tools are wrapped in ``{"type": "function", "function": {...}}``."""

    async def test_parameters_wrapped_in_function_object(self) -> None:
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_Completion())
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="test",
            messages=[LLMMessage(role="user", content="hi")],
            tools=[
                {
                    "name": "calc",
                    "description": "Calculate",
                    "parameters": {
                        "type": "object",
                        "properties": {"expr": {"type": "string"}},
                        "required": ["expr"],
                    },
                }
            ],
        )
        await backend.generate(prompt)

        call_kwargs = client.chat.completions.create.call_args[1]
        tools_sent = call_kwargs["tools"]
        assert len(tools_sent) == 1

        tool = tools_sent[0]
        assert tool["type"] == "function"
        assert "function" in tool
        assert tool["function"]["name"] == "calc"
        assert tool["function"]["description"] == "Calculate"
        assert tool["function"]["parameters"]["type"] == "object"

    async def test_multiple_tools_all_wrapped(self) -> None:
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_Completion())
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="test",
            messages=[LLMMessage(role="user", content="hi")],
            tools=[
                {"name": "a", "description": "A", "parameters": {"type": "object"}},
                {"name": "b", "description": "B", "parameters": {"type": "object"}},
            ],
        )
        await backend.generate(prompt)

        tools_sent = client.chat.completions.create.call_args[1]["tools"]
        assert len(tools_sent) == 2
        for t in tools_sent:
            assert t["type"] == "function"
            assert "function" in t
            assert "name" in t["function"]


# ---------------------------------------------------------------------------
# Multi-turn message format tests
# ---------------------------------------------------------------------------


class TestOpenAIMultiTurnMessages:
    """Verify tool_calls and tool_call_id in OpenAI message format."""

    async def test_assistant_tool_calls_formatted_correctly(self) -> None:
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_Completion())
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="test",
            messages=[
                LLMMessage(role="user", content="What is 7 * 6?"),
                LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="call_1", name="calc", arguments={"expr": "7*6"})],
                ),
                LLMMessage(role="tool", content='{"result": 42}', tool_call_id="call_1"),
            ],
        )
        await backend.generate(prompt)

        messages_sent = client.chat.completions.create.call_args[1]["messages"]

        # Message 0: developer (system)
        assert messages_sent[0]["role"] == "developer"

        # Message 1: user
        assert messages_sent[1]["role"] == "user"
        assert messages_sent[1]["content"] == "What is 7 * 6?"

        # Message 2: assistant with tool_calls
        assistant_msg = messages_sent[2]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] is None  # empty string becomes None
        tc_list = assistant_msg["tool_calls"]
        assert len(tc_list) == 1
        assert tc_list[0]["id"] == "call_1"
        assert tc_list[0]["type"] == "function"
        assert tc_list[0]["function"]["name"] == "calc"
        assert json.loads(tc_list[0]["function"]["arguments"]) == {"expr": "7*6"}

        # Message 3: tool result with tool_call_id
        tool_msg = messages_sent[3]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_1"
        assert tool_msg["content"] == '{"result": 42}'

    async def test_plain_assistant_message(self) -> None:
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_Completion())
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="test",
            messages=[
                LLMMessage(role="user", content="hi"),
                LLMMessage(role="assistant", content="hello"),
            ],
        )
        await backend.generate(prompt)

        messages_sent = client.chat.completions.create.call_args[1]["messages"]
        assert messages_sent[2] == {"role": "assistant", "content": "hello"}
