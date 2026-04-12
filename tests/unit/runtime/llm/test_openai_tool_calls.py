"""Unit tests for OpenAIBackend native function calling (E8-B).

Mocks the OpenAI SDK to verify tool_calls parsing, finish_reason
mapping, tool_choice pass-through, and retry on transient errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.llm.retry import RetryConfig

# ---------------------------------------------------------------------------
# Fake OpenAI SDK types
# ---------------------------------------------------------------------------


@dataclass
class _Function:
    name: str = ""
    arguments: str = ""


@dataclass
class _ToolCallObj:
    id: str = ""
    function: _Function = field(default_factory=_Function)


@dataclass
class _Message:
    content: str | None = ""
    tool_calls: list[_ToolCallObj] | None = None


@dataclass
class _Choice:
    message: _Message = field(default_factory=_Message)
    finish_reason: str = "stop"


@dataclass
class _Usage:
    prompt_tokens: int = 10
    completion_tokens: int = 20


@dataclass
class _Completion:
    choices: list[_Choice] = field(default_factory=list)
    model: str = "gpt-5.4-mini"
    usage: _Usage = field(default_factory=_Usage)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_prompt() -> LLMPrompt:
    return LLMPrompt(
        system="You are a helpful assistant.",
        messages=[LLMMessage(role="user", content="What is the weather?")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            }
        ],
    )


def _make_backend(client_mock: Any, retry: RetryConfig | None = None) -> Any:
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        from agenticapi.runtime.llm.openai import OpenAIBackend

        backend = OpenAIBackend(retry=retry or RetryConfig(max_retries=0, retryable_exceptions=()))
        backend._client = client_mock
        return backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOpenAIToolCallRoundTrip:
    async def test_tool_calls_parsed(self) -> None:
        completion = _Completion(
            choices=[
                _Choice(
                    message=_Message(
                        content=None,
                        tool_calls=[
                            _ToolCallObj(
                                id="call_1", function=_Function(name="get_weather", arguments='{"city":"NYC"}')
                            ),
                        ],
                    ),
                    finish_reason="tool_calls",
                ),
            ],
        )
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=completion)
        backend = _make_backend(client)

        response = await backend.generate(_tool_prompt())

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].id == "call_1"
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "NYC"}
        assert response.finish_reason == "tool_calls"

    async def test_text_response_no_tool_calls(self) -> None:
        completion = _Completion(
            choices=[
                _Choice(
                    message=_Message(content="It's sunny.", tool_calls=None),
                    finish_reason="stop",
                ),
            ],
        )
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=completion)
        backend = _make_backend(client)

        prompt = LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")])
        response = await backend.generate(prompt)

        assert response.tool_calls == []
        assert response.finish_reason == "stop"
        assert response.content == "It's sunny."

    async def test_multiple_tool_calls(self) -> None:
        completion = _Completion(
            choices=[
                _Choice(
                    message=_Message(
                        content=None,
                        tool_calls=[
                            _ToolCallObj(id="c1", function=_Function(name="get_weather", arguments='{"city":"NYC"}')),
                            _ToolCallObj(id="c2", function=_Function(name="get_weather", arguments='{"city":"LA"}')),
                        ],
                    ),
                    finish_reason="tool_calls",
                ),
            ],
        )
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=completion)
        backend = _make_backend(client)

        response = await backend.generate(_tool_prompt())
        assert len(response.tool_calls) == 2

    async def test_invalid_json_arguments_handled(self) -> None:
        completion = _Completion(
            choices=[
                _Choice(
                    message=_Message(
                        content=None,
                        tool_calls=[
                            _ToolCallObj(id="c1", function=_Function(name="t", arguments="not json")),
                        ],
                    ),
                    finish_reason="tool_calls",
                ),
            ],
        )
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=completion)
        backend = _make_backend(client)

        response = await backend.generate(_tool_prompt())
        assert response.tool_calls[0].arguments == {}


class TestOpenAIToolChoice:
    async def test_tool_choice_passed_through(self) -> None:
        completion = _Completion(
            choices=[_Choice(message=_Message(content="ok"), finish_reason="stop")],
        )
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=completion)
        backend = _make_backend(client)

        prompt = LLMPrompt(
            system="x",
            messages=[LLMMessage(role="user", content="hi")],
            tools=[{"type": "function", "function": {"name": "t", "description": "t", "parameters": {}}}],
            tool_choice="required",
        )
        await backend.generate(prompt)
        call_kwargs = client.chat.completions.create.call_args[1]
        assert call_kwargs["tool_choice"] == "required"


class TestOpenAIRetry:
    @patch("agenticapi.runtime.llm.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_rate_limit(self, mock_sleep: AsyncMock) -> None:
        rate_limit_exc = type("RateLimitError", (Exception,), {})()
        completion = _Completion(
            choices=[_Choice(message=_Message(content="ok"), finish_reason="stop")],
        )
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=[rate_limit_exc, completion])
        backend = _make_backend(
            client,
            retry=RetryConfig(max_retries=2, retryable_exceptions=(type(rate_limit_exc),), jitter=False),
        )

        response = await backend.generate(LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")]))
        assert response.content == "ok"
        assert client.chat.completions.create.call_count == 2
