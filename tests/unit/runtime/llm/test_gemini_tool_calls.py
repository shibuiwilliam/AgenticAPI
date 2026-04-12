"""Unit tests for GeminiBackend native function calling (E8-C).

Mocks the google-genai SDK to verify function_call part parsing,
finish_reason mapping, tool conversion, and retry on transient errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.llm.retry import RetryConfig

# ---------------------------------------------------------------------------
# Fake Gemini SDK types
# ---------------------------------------------------------------------------


@dataclass
class _FunctionCall:
    name: str = ""
    args: dict[str, Any] | None = None


@dataclass
class _Part:
    text: str | None = None
    function_call: _FunctionCall | None = None


@dataclass
class _Content:
    parts: list[_Part] = field(default_factory=list)
    role: str = "model"


@dataclass
class _Candidate:
    content: _Content = field(default_factory=_Content)
    finish_reason: str = "STOP"


@dataclass
class _UsageMetadata:
    prompt_token_count: int = 10
    candidates_token_count: int = 20


@dataclass
class _Response:
    candidates: list[_Candidate] = field(default_factory=list)
    usage_metadata: _UsageMetadata = field(default_factory=_UsageMetadata)

    @property
    def text(self) -> str | None:
        for c in self.candidates:
            for p in c.content.parts:
                if p.text:
                    return p.text
        return None


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
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
            }
        ],
    )


def _make_backend(client_mock: Any, retry: RetryConfig | None = None) -> Any:
    with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}):
        from agenticapi.runtime.llm.gemini import GeminiBackend

        backend = GeminiBackend(retry=retry or RetryConfig(max_retries=0, retryable_exceptions=()))
        backend._client = client_mock
        return backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGeminiFunctionCallRoundTrip:
    async def test_function_call_parsed(self) -> None:
        resp = _Response(
            candidates=[
                _Candidate(
                    content=_Content(
                        parts=[_Part(function_call=_FunctionCall(name="get_weather", args={"city": "Tokyo"}))]
                    ),
                    finish_reason="STOP",
                )
            ],
        )
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=resp)
        backend = _make_backend(client)

        response = await backend.generate(_tool_prompt())

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_weather"
        assert response.tool_calls[0].arguments == {"city": "Tokyo"}
        assert response.finish_reason == "tool_calls"
        assert response.content == ""

    async def test_text_response_no_tool_calls(self) -> None:
        resp = _Response(
            candidates=[
                _Candidate(
                    content=_Content(parts=[_Part(text="It's sunny.")]),
                    finish_reason="STOP",
                )
            ],
        )
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=resp)
        backend = _make_backend(client)

        prompt = LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")])
        response = await backend.generate(prompt)

        assert response.tool_calls == []
        assert response.finish_reason == "stop"
        assert response.content == "It's sunny."

    async def test_mixed_text_and_function_call(self) -> None:
        resp = _Response(
            candidates=[
                _Candidate(
                    content=_Content(
                        parts=[
                            _Part(text="Let me check. "),
                            _Part(function_call=_FunctionCall(name="get_weather", args={"city": "LA"})),
                        ]
                    ),
                    finish_reason="STOP",
                )
            ],
        )
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=resp)
        backend = _make_backend(client)

        response = await backend.generate(_tool_prompt())
        assert response.content == "Let me check. "
        assert len(response.tool_calls) == 1
        assert response.finish_reason == "tool_calls"

    async def test_max_tokens_finish_reason(self) -> None:
        resp = _Response(
            candidates=[
                _Candidate(
                    content=_Content(parts=[_Part(text="partial")]),
                    finish_reason="MAX_TOKENS",
                )
            ],
        )
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=resp)
        backend = _make_backend(client)

        prompt = LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")])
        response = await backend.generate(prompt)
        assert response.finish_reason == "length"

    async def test_safety_finish_reason(self) -> None:
        resp = _Response(
            candidates=[
                _Candidate(
                    content=_Content(parts=[_Part(text="")]),
                    finish_reason="SAFETY",
                )
            ],
        )
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=resp)
        backend = _make_backend(client)

        prompt = LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")])
        response = await backend.generate(prompt)
        assert response.finish_reason == "content_filter"


class TestGeminiToolConversion:
    async def test_tools_passed_to_api(self) -> None:
        resp = _Response(
            candidates=[_Candidate(content=_Content(parts=[_Part(text="ok")]), finish_reason="STOP")],
        )
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=resp)
        backend = _make_backend(client)

        await backend.generate(_tool_prompt())

        call_kwargs = client.aio.models.generate_content.call_args[1]
        config = call_kwargs["config"]
        # Verify tools were set on the config
        assert config.tools is not None


class TestGeminiRetry:
    @patch("agenticapi.runtime.llm.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_resource_exhausted(self, mock_sleep: AsyncMock) -> None:
        resource_exc = type("ResourceExhausted", (Exception,), {})()
        resp = _Response(
            candidates=[_Candidate(content=_Content(parts=[_Part(text="ok")]), finish_reason="STOP")],
        )
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(side_effect=[resource_exc, resp])
        backend = _make_backend(
            client,
            retry=RetryConfig(max_retries=2, retryable_exceptions=(type(resource_exc),), jitter=False),
        )

        response = await backend.generate(LLMPrompt(system="x", messages=[LLMMessage(role="user", content="hi")]))
        assert response.content == "ok"
        assert client.aio.models.generate_content.call_count == 2
