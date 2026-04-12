"""Unit tests for AnthropicBackend native function calling (E8-A).

Mocks the Anthropic SDK to verify tool_use block parsing, finish_reason
mapping, tool_choice pass-through, and retry on transient errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.llm.retry import RetryConfig

# ---------------------------------------------------------------------------
# Fake Anthropic SDK types
# ---------------------------------------------------------------------------


@dataclass
class _TextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class _ToolUseBlock:
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict[str, Any] | None = None


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_prompt() -> LLMPrompt:
    return LLMPrompt(
        system="You are a helpful assistant.",
        messages=[LLMMessage(role="user", content="What is the weather?")],
        tools=[
            {
                "name": "get_weather",
                "description": "Get current weather",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
            }
        ],
    )


def _make_backend(client_mock: AsyncMock, retry: RetryConfig | None = None) -> Any:
    """Construct an AnthropicBackend with a pre-injected mock client."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        from agenticapi.runtime.llm.anthropic import AnthropicBackend

        backend = AnthropicBackend(retry=retry or RetryConfig(max_retries=0, retryable_exceptions=()))
        backend._client = client_mock
        return backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnthropicToolUseRoundTrip:
    async def test_tool_use_response_parsed(self) -> None:
        """A response with a tool_use block yields ToolCall + finish_reason."""
        msg = _Message(
            content=[
                _ToolUseBlock(type="tool_use", id="call_1", name="get_weather", input={"city": "Tokyo"}),
            ],
            stop_reason="tool_use",
        )
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        response = await backend.generate(_tool_prompt())

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].id == "call_1"
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "Tokyo"}
        assert response.finish_reason == "tool_calls"
        assert response.content == ""

    async def test_text_response_no_tool_calls(self) -> None:
        """A plain text response has empty tool_calls and finish_reason='stop'."""
        msg = _Message(
            content=[_TextBlock(text="The weather is sunny.")],
            stop_reason="end_turn",
        )
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")])
        response = await backend.generate(prompt)

        assert response.tool_calls == []
        assert response.finish_reason == "stop"
        assert response.content == "The weather is sunny."

    async def test_mixed_text_and_tool_use(self) -> None:
        """Response with both text and tool_use blocks."""
        msg = _Message(
            content=[
                _TextBlock(text="Let me check. "),
                _ToolUseBlock(type="tool_use", id="call_2", name="get_weather", input={"city": "NYC"}),
            ],
            stop_reason="tool_use",
        )
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        response = await backend.generate(_tool_prompt())

        assert response.content == "Let me check. "
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.finish_reason == "tool_calls"

    async def test_max_tokens_finish_reason(self) -> None:
        """stop_reason='max_tokens' maps to finish_reason='length'."""
        msg = _Message(content=[_TextBlock(text="partial")], stop_reason="max_tokens")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")])
        response = await backend.generate(prompt)
        assert response.finish_reason == "length"


class TestAnthropicToolChoice:
    async def test_tool_choice_auto(self) -> None:
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="x",
            messages=[LLMMessage(role="user", content="hi")],
            tools=[{"name": "t", "description": "t", "input_schema": {}}],
            tool_choice="auto",
        )
        await backend.generate(prompt)
        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["tool_choice"] == {"type": "auto"}

    async def test_tool_choice_required(self) -> None:
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="x",
            messages=[LLMMessage(role="user", content="hi")],
            tools=[{"name": "t", "description": "t", "input_schema": {}}],
            tool_choice="required",
        )
        await backend.generate(prompt)
        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["tool_choice"] == {"type": "any"}

    async def test_tool_choice_none_removes_tools(self) -> None:
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=msg)
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="x",
            messages=[LLMMessage(role="user", content="hi")],
            tools=[{"name": "t", "description": "t", "input_schema": {}}],
            tool_choice="none",
        )
        await backend.generate(prompt)
        call_kwargs = client.messages.create.call_args[1]
        assert "tools" not in call_kwargs


class TestAnthropicRetry:
    @patch("agenticapi.runtime.llm.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_rate_limit(self, mock_sleep: AsyncMock) -> None:
        """Retry fires on RateLimitError, then succeeds."""
        # Create a fake RateLimitError
        rate_limit_exc = type("RateLimitError", (Exception,), {})()
        msg = _Message(content=[_TextBlock(text="ok")], stop_reason="end_turn")

        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=[rate_limit_exc, msg])
        backend = _make_backend(
            client,
            retry=RetryConfig(max_retries=2, retryable_exceptions=(type(rate_limit_exc),), jitter=False),
        )

        response = await backend.generate(LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")]))
        assert response.content == "ok"
        assert client.messages.create.call_count == 2
