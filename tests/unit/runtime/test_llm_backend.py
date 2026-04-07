"""Tests for MockBackend."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.llm.mock import MockBackend


def _make_prompt(user_msg: str = "test") -> LLMPrompt:
    return LLMPrompt(
        system="You are a test assistant.",
        messages=[LLMMessage(role="user", content=user_msg)],
    )


class TestMockBackendGenerate:
    async def test_returns_first_response(self) -> None:
        backend = MockBackend(responses=["hello"])
        response = await backend.generate(_make_prompt())
        assert response.content == "hello"
        assert response.model == "mock"

    async def test_returns_responses_in_order(self) -> None:
        backend = MockBackend(responses=["first", "second", "third"])
        r1 = await backend.generate(_make_prompt())
        r2 = await backend.generate(_make_prompt())
        r3 = await backend.generate(_make_prompt())
        assert r1.content == "first"
        assert r2.content == "second"
        assert r3.content == "third"

    async def test_raises_when_exhausted(self) -> None:
        backend = MockBackend(responses=["only_one"])
        await backend.generate(_make_prompt())
        with pytest.raises(CodeGenerationError, match="no more responses"):
            await backend.generate(_make_prompt())

    async def test_raises_when_empty(self) -> None:
        backend = MockBackend()
        with pytest.raises(CodeGenerationError, match="no more responses"):
            await backend.generate(_make_prompt())

    async def test_usage_populated(self) -> None:
        backend = MockBackend(responses=["response text"])
        response = await backend.generate(_make_prompt())
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0


class TestMockBackendCallTracking:
    async def test_call_count(self) -> None:
        backend = MockBackend(responses=["a", "b"])
        assert backend.call_count == 0
        await backend.generate(_make_prompt())
        assert backend.call_count == 1
        await backend.generate(_make_prompt())
        assert backend.call_count == 2

    async def test_prompts_recorded(self) -> None:
        backend = MockBackend(responses=["resp"])
        prompt = _make_prompt("my question")
        await backend.generate(prompt)
        assert len(backend.prompts) == 1
        assert backend.prompts[0].messages[0].content == "my question"


class TestMockBackendAddResponse:
    async def test_add_response(self) -> None:
        backend = MockBackend()
        backend.add_response("dynamic response")
        response = await backend.generate(_make_prompt())
        assert response.content == "dynamic response"


class TestMockBackendStream:
    async def test_generate_stream_yields_chunks(self) -> None:
        backend = MockBackend(responses=["hello world"])
        chunks = []
        async for chunk in backend.generate_stream(_make_prompt()):
            chunks.append(chunk)
        assert len(chunks) >= 1
        # Last chunk should be final
        assert chunks[-1].is_final is True
        # Reconstruct the full content
        full = "".join(c.content for c in chunks)
        assert full == "hello world"

    async def test_generate_stream_single_word(self) -> None:
        backend = MockBackend(responses=["hello"])
        chunks = []
        async for chunk in backend.generate_stream(_make_prompt()):
            chunks.append(chunk)
        assert len(chunks) == 1
        assert chunks[0].content == "hello"
        assert chunks[0].is_final is True


class TestMockBackendModelName:
    def test_model_name(self) -> None:
        backend = MockBackend()
        assert backend.model_name == "mock"
