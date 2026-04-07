"""Tests for OpenAIBackend."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.llm.openai import OpenAIBackend


def _make_prompt(user_msg: str = "test") -> LLMPrompt:
    return LLMPrompt(
        system="You are a test assistant.",
        messages=[LLMMessage(role="user", content=user_msg)],
    )


def _make_completion(content: str = "hello", model: str = "gpt-5.4-mini") -> MagicMock:
    """Create a mock OpenAI ChatCompletion response."""
    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5

    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = usage
    completion.model = model
    return completion


def _create_backend() -> OpenAIBackend:
    """Create an OpenAIBackend with a fake API key."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        return OpenAIBackend()


class TestOpenAIBackendInit:
    def test_raises_without_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True), pytest.raises(ValueError, match="OpenAI API key"):
            OpenAIBackend()

    def test_model_name(self) -> None:
        backend = _create_backend()
        assert backend.model_name == "gpt-5.4-mini"

    def test_custom_model(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            backend = OpenAIBackend(model="gpt-5.4-mini-mini")
        assert backend.model_name == "gpt-5.4-mini-mini"


class TestOpenAIBackendGenerate:
    async def test_returns_content(self) -> None:
        backend = _create_backend()
        mock_completion = _make_completion("generated code")
        backend._client.chat.completions.create = AsyncMock(return_value=mock_completion)

        response = await backend.generate(_make_prompt())
        assert response.content == "generated code"
        assert response.model == "gpt-5.4-mini"

    async def test_returns_usage(self) -> None:
        backend = _create_backend()
        mock_completion = _make_completion()
        backend._client.chat.completions.create = AsyncMock(return_value=mock_completion)

        response = await backend.generate(_make_prompt())
        assert response.usage.input_tokens == 10
        assert response.usage.output_tokens == 5

    async def test_builds_messages_with_developer_role(self) -> None:
        backend = _create_backend()
        mock_completion = _make_completion()
        backend._client.chat.completions.create = AsyncMock(return_value=mock_completion)

        prompt = LLMPrompt(
            system="System prompt",
            messages=[LLMMessage(role="user", content="Hello")],
            temperature=0.5,
        )
        await backend.generate(prompt)

        call_kwargs = backend._client.chat.completions.create.call_args[1]
        assert call_kwargs["messages"][0] == {"role": "developer", "content": "System prompt"}
        assert call_kwargs["messages"][1] == {"role": "user", "content": "Hello"}
        assert call_kwargs["temperature"] == 0.5

    async def test_filters_system_role_from_messages(self) -> None:
        backend = _create_backend()
        mock_completion = _make_completion()
        backend._client.chat.completions.create = AsyncMock(return_value=mock_completion)

        prompt = LLMPrompt(
            system="System",
            messages=[
                LLMMessage(role="system", content="should be filtered"),
                LLMMessage(role="user", content="Hello"),
            ],
        )
        await backend.generate(prompt)

        call_kwargs = backend._client.chat.completions.create.call_args[1]
        # developer (system) + user, no extra system message
        assert len(call_kwargs["messages"]) == 2

    async def test_passes_tools(self) -> None:
        backend = _create_backend()
        mock_completion = _make_completion()
        backend._client.chat.completions.create = AsyncMock(return_value=mock_completion)

        tools = [{"type": "function", "function": {"name": "get_weather"}}]
        prompt = LLMPrompt(system="sys", messages=[LLMMessage(role="user", content="hi")], tools=tools)
        await backend.generate(prompt)

        call_kwargs = backend._client.chat.completions.create.call_args[1]
        assert call_kwargs["tools"] == tools

    async def test_raises_code_generation_error_on_failure(self) -> None:
        backend = _create_backend()
        backend._client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

        with pytest.raises(CodeGenerationError, match="OpenAI API call failed"):
            await backend.generate(_make_prompt())

    async def test_reraises_code_generation_error(self) -> None:
        backend = _create_backend()
        backend._client.chat.completions.create = AsyncMock(side_effect=CodeGenerationError("already wrapped"))

        with pytest.raises(CodeGenerationError, match="already wrapped"):
            await backend.generate(_make_prompt())

    async def test_handles_none_content(self) -> None:
        backend = _create_backend()
        mock_completion = _make_completion()
        mock_completion.choices[0].message.content = None
        backend._client.chat.completions.create = AsyncMock(return_value=mock_completion)

        response = await backend.generate(_make_prompt())
        assert response.content == ""

    async def test_handles_none_usage(self) -> None:
        backend = _create_backend()
        mock_completion = _make_completion()
        mock_completion.usage = None
        backend._client.chat.completions.create = AsyncMock(return_value=mock_completion)

        response = await backend.generate(_make_prompt())
        assert response.usage.input_tokens == 0
        assert response.usage.output_tokens == 0


class TestOpenAIBackendStream:
    async def test_yields_chunks(self) -> None:
        backend = _create_backend()

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "hello "

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = "world"

        async def mock_stream() -> Any:
            yield chunk1
            yield chunk2

        backend._client.chat.completions.create = AsyncMock(return_value=mock_stream())

        chunks = []
        async for chunk in backend.generate_stream(_make_prompt()):
            chunks.append(chunk)

        assert len(chunks) == 3  # 2 content + 1 final
        assert chunks[0].content == "hello "
        assert chunks[1].content == "world"
        assert chunks[2].is_final is True
        assert chunks[2].content == ""

    async def test_skips_empty_delta(self) -> None:
        backend = _create_backend()

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "data"

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = None

        async def mock_stream() -> Any:
            yield chunk1
            yield chunk2

        backend._client.chat.completions.create = AsyncMock(return_value=mock_stream())

        chunks = []
        async for chunk in backend.generate_stream(_make_prompt()):
            chunks.append(chunk)

        # Only "data" + final empty
        assert len(chunks) == 2
        assert chunks[0].content == "data"

    async def test_raises_on_stream_error(self) -> None:
        backend = _create_backend()
        backend._client.chat.completions.create = AsyncMock(side_effect=RuntimeError("stream failed"))

        with pytest.raises(CodeGenerationError, match="OpenAI streaming API call failed"):
            async for _ in backend.generate_stream(_make_prompt()):
                pass
