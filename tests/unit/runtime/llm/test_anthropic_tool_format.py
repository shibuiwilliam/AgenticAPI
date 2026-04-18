"""Unit tests for AnthropicBackend tool format translation.

Verifies that:
- Tool definitions are translated to Anthropic's ``input_schema`` format.
- Multi-turn conversations with tool_calls and tool_call_id are
  correctly converted to Anthropic's ``tool_use`` / ``tool_result``
  content-block format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt, ToolCall
from agenticapi.runtime.llm.retry import RetryConfig

# ---------------------------------------------------------------------------
# Fake Anthropic SDK types
# ---------------------------------------------------------------------------


@dataclass
class _TextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class _Usage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class _Message:
    content: list[Any] = None  # type: ignore[assignment]
    model: str = "claude-sonnet-4-6"
    stop_reason: str = "end_turn"
    usage: _Usage = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.content is None:
            self.content = []
        if self.usage is None:
            self.usage = _Usage()


def _make_backend(client_mock: MagicMock) -> Any:
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        from agenticapi.runtime.llm.anthropic import AnthropicBackend

        backend = AnthropicBackend(retry=RetryConfig(max_retries=0, retryable_exceptions=()))
        backend._client = client_mock
        return backend


# ---------------------------------------------------------------------------
# Tool definition format tests
# ---------------------------------------------------------------------------


class TestAnthropicToolDefinitionFormat:
    """Verify tools use ``input_schema`` key, not ``parameters``."""

    async def test_parameters_translated_to_input_schema(self) -> None:
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
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

        call_kwargs = client.messages.create.call_args[1]
        tools_sent = call_kwargs["tools"]
        assert len(tools_sent) == 1
        tool = tools_sent[0]
        # Must use input_schema, not parameters.
        assert "input_schema" in tool
        assert "parameters" not in tool
        assert tool["input_schema"]["type"] == "object"
        assert tool["name"] == "calc"
        assert tool["description"] == "Calculate"

    async def test_input_schema_key_passthrough(self) -> None:
        """If tool already uses input_schema key, it still works."""
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="test",
            messages=[LLMMessage(role="user", content="hi")],
            tools=[
                {
                    "name": "search",
                    "description": "Search",
                    "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                }
            ],
        )
        await backend.generate(prompt)

        tool = client.messages.create.call_args[1]["tools"][0]
        assert tool["input_schema"]["type"] == "object"

    async def test_multiple_tools_all_translated(self) -> None:
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
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

        tools_sent = client.messages.create.call_args[1]["tools"]
        assert len(tools_sent) == 2
        for t in tools_sent:
            assert "input_schema" in t
            assert "parameters" not in t


# ---------------------------------------------------------------------------
# Multi-turn message format tests
# ---------------------------------------------------------------------------


class TestAnthropicMultiTurnMessages:
    """Verify assistant tool_calls and tool results use Anthropic content-block format."""

    async def test_assistant_tool_calls_become_tool_use_blocks(self) -> None:
        msg = _Message(content=[_TextBlock(text="done")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="test",
            messages=[
                LLMMessage(role="user", content="What is 7 * 6?"),
                LLMMessage(
                    role="assistant",
                    content="Let me calculate.",
                    tool_calls=[ToolCall(id="tc_1", name="calc", arguments={"expr": "7*6"})],
                ),
                LLMMessage(role="tool", content='{"result": 42}', tool_call_id="tc_1"),
            ],
        )
        await backend.generate(prompt)

        messages_sent = client.messages.create.call_args[1]["messages"]

        # Message 0: user
        assert messages_sent[0]["role"] == "user"
        assert messages_sent[0]["content"] == "What is 7 * 6?"

        # Message 1: assistant with tool_use content blocks
        assistant_msg = messages_sent[1]
        assert assistant_msg["role"] == "assistant"
        blocks = assistant_msg["content"]
        assert isinstance(blocks, list)
        assert blocks[0] == {"type": "text", "text": "Let me calculate."}
        assert blocks[1]["type"] == "tool_use"
        assert blocks[1]["id"] == "tc_1"
        assert blocks[1]["name"] == "calc"
        assert blocks[1]["input"] == {"expr": "7*6"}

        # Message 2: tool result as user message with tool_result block
        tool_msg = messages_sent[2]
        assert tool_msg["role"] == "user"
        assert tool_msg["content"][0]["type"] == "tool_result"
        assert tool_msg["content"][0]["tool_use_id"] == "tc_1"
        assert tool_msg["content"][0]["content"] == '{"result": 42}'

    async def test_assistant_without_tool_calls_is_plain(self) -> None:
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="test",
            messages=[
                LLMMessage(role="user", content="hi"),
                LLMMessage(role="assistant", content="hello"),
                LLMMessage(role="user", content="bye"),
            ],
        )
        await backend.generate(prompt)

        messages_sent = client.messages.create.call_args[1]["messages"]
        assert messages_sent[1] == {"role": "assistant", "content": "hello"}

    async def test_tool_without_tool_call_id_is_plain(self) -> None:
        """A tool message without tool_call_id falls through to plain format."""
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="test",
            messages=[
                LLMMessage(role="user", content="hi"),
                LLMMessage(role="tool", content="some result"),
            ],
        )
        await backend.generate(prompt)

        messages_sent = client.messages.create.call_args[1]["messages"]
        assert messages_sent[1] == {"role": "tool", "content": "some result"}
