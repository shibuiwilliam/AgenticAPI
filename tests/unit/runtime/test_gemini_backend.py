"""Tests for GeminiBackend."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.llm.gemini import GeminiBackend


def _make_prompt(user_msg: str = "test") -> LLMPrompt:
    return LLMPrompt(
        system="You are a test assistant.",
        messages=[LLMMessage(role="user", content=user_msg)],
    )


def _make_response(text: str = "hello") -> MagicMock:
    """Create a mock Gemini GenerateContentResponse."""
    usage_meta = MagicMock()
    usage_meta.prompt_token_count = 10
    usage_meta.candidates_token_count = 5

    response = MagicMock()
    response.text = text
    response.usage_metadata = usage_meta
    return response


def _create_backend() -> GeminiBackend:
    """Create a GeminiBackend with a fake API key."""
    with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}):
        return GeminiBackend()


class TestGeminiBackendInit:
    def test_raises_without_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True), pytest.raises(ValueError, match="Google API key"):
            GeminiBackend()

    def test_model_name(self) -> None:
        backend = _create_backend()
        assert backend.model_name == "gemini-2.5-flash"

    def test_custom_model(self) -> None:
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}):
            backend = GeminiBackend(model="gemini-2.5-pro")
        assert backend.model_name == "gemini-2.5-pro"


class TestGeminiBackendGenerate:
    async def test_returns_content(self) -> None:
        backend = _create_backend()
        mock_response = _make_response("generated code")
        backend._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        response = await backend.generate(_make_prompt())
        assert response.content == "generated code"
        assert response.model == "gemini-2.5-flash"

    async def test_returns_usage(self) -> None:
        backend = _create_backend()
        mock_response = _make_response()
        backend._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        response = await backend.generate(_make_prompt())
        assert response.usage.input_tokens == 10
        assert response.usage.output_tokens == 5

    async def test_passes_system_instruction_in_config(self) -> None:
        backend = _create_backend()
        mock_response = _make_response()
        backend._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        prompt = LLMPrompt(
            system="Be helpful",
            messages=[LLMMessage(role="user", content="Hello")],
            temperature=0.7,
            max_tokens=2048,
        )
        await backend.generate(prompt)

        call_kwargs = backend._client.aio.models.generate_content.call_args[1]
        assert call_kwargs["model"] == "gemini-2.5-flash"
        config = call_kwargs["config"]
        assert config.system_instruction == "Be helpful"
        assert config.temperature == 0.7
        assert config.max_output_tokens == 2048

    async def test_maps_assistant_role_to_model(self) -> None:
        backend = _create_backend()
        mock_response = _make_response()
        backend._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        prompt = LLMPrompt(
            system="sys",
            messages=[
                LLMMessage(role="user", content="Hello"),
                LLMMessage(role="assistant", content="Hi there"),
                LLMMessage(role="user", content="More"),
            ],
        )
        await backend.generate(prompt)

        call_kwargs = backend._client.aio.models.generate_content.call_args[1]
        contents = call_kwargs["contents"]
        assert len(contents) == 3
        assert contents[0].role == "user"
        assert contents[1].role == "model"
        assert contents[2].role == "user"

    async def test_filters_system_messages(self) -> None:
        backend = _create_backend()
        mock_response = _make_response()
        backend._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        prompt = LLMPrompt(
            system="sys",
            messages=[
                LLMMessage(role="system", content="filtered"),
                LLMMessage(role="user", content="Hello"),
            ],
        )
        await backend.generate(prompt)

        call_kwargs = backend._client.aio.models.generate_content.call_args[1]
        contents = call_kwargs["contents"]
        assert len(contents) == 1
        assert contents[0].role == "user"

    async def test_raises_code_generation_error_on_failure(self) -> None:
        backend = _create_backend()
        backend._client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("API down"))

        with pytest.raises(CodeGenerationError, match="Gemini API call failed"):
            await backend.generate(_make_prompt())

    async def test_reraises_code_generation_error(self) -> None:
        backend = _create_backend()
        backend._client.aio.models.generate_content = AsyncMock(side_effect=CodeGenerationError("already wrapped"))

        with pytest.raises(CodeGenerationError, match="already wrapped"):
            await backend.generate(_make_prompt())

    async def test_handles_none_text(self) -> None:
        backend = _create_backend()
        mock_response = _make_response()
        mock_response.text = None
        backend._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        response = await backend.generate(_make_prompt())
        assert response.content == ""

    async def test_handles_none_usage_metadata(self) -> None:
        backend = _create_backend()
        mock_response = _make_response()
        mock_response.usage_metadata = None
        backend._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        response = await backend.generate(_make_prompt())
        assert response.usage.input_tokens == 0
        assert response.usage.output_tokens == 0


class TestGeminiBackendStream:
    async def test_yields_chunks(self) -> None:
        backend = _create_backend()

        chunk1 = MagicMock()
        chunk1.text = "hello "

        chunk2 = MagicMock()
        chunk2.text = "world"

        async def mock_stream() -> Any:
            yield chunk1
            yield chunk2

        backend._client.aio.models.generate_content_stream = AsyncMock(return_value=mock_stream())

        chunks = []
        async for chunk in backend.generate_stream(_make_prompt()):
            chunks.append(chunk)

        assert len(chunks) == 3  # 2 content + 1 final
        assert chunks[0].content == "hello "
        assert chunks[1].content == "world"
        assert chunks[2].is_final is True
        assert chunks[2].content == ""

    async def test_skips_empty_text(self) -> None:
        backend = _create_backend()

        chunk1 = MagicMock()
        chunk1.text = "data"

        chunk2 = MagicMock()
        chunk2.text = None

        async def mock_stream() -> Any:
            yield chunk1
            yield chunk2

        backend._client.aio.models.generate_content_stream = AsyncMock(return_value=mock_stream())

        chunks = []
        async for chunk in backend.generate_stream(_make_prompt()):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].content == "data"

    async def test_raises_on_stream_error(self) -> None:
        backend = _create_backend()

        async def failing_stream() -> Any:
            raise RuntimeError("stream failed")
            yield

        backend._client.aio.models.generate_content_stream = AsyncMock(return_value=failing_stream())

        with pytest.raises(CodeGenerationError, match="Gemini streaming API call failed"):
            async for _ in backend.generate_stream(_make_prompt()):
                pass
