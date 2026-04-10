"""Tests for :class:`ClaudeAgentSDKBackend`."""

from __future__ import annotations

from typing import Any

import pytest
from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

from agenticapi_claude_agent_sdk.backend import ClaudeAgentSDKBackend


def _prompt(user_text: str = "say hi") -> LLMPrompt:
    return LLMPrompt(
        system="be helpful",
        messages=[LLMMessage(role="user", content=user_text)],
    )


async def test_generate_returns_result_text(stub_messages: Any) -> None:
    from tests.conftest import StubResultMessage

    stub_messages(
        [
            StubResultMessage(
                result="hi!",
                usage={"input_tokens": 5, "output_tokens": 2},
            )
        ]
    )

    backend = ClaudeAgentSDKBackend(model="stub-model")
    response = await backend.generate(_prompt())

    assert response.content == "hi!"
    assert response.usage.input_tokens == 5
    assert response.usage.output_tokens == 2
    assert response.model in ("stub-model", "")  # depends on AssistantMessage emission


async def test_generate_raises_on_error(stub_messages: Any) -> None:
    from tests.conftest import StubResultMessage

    stub_messages(
        [
            StubResultMessage(is_error=True, errors=["bad"], subtype="error_during_execution"),
        ]
    )

    backend = ClaudeAgentSDKBackend()
    with pytest.raises(CodeGenerationError):
        await backend.generate(_prompt())


async def test_generate_stream_emits_full_response_then_final_chunk(stub_messages: Any) -> None:
    from tests.conftest import StubResultMessage

    stub_messages([StubResultMessage(result="hello world")])
    backend = ClaudeAgentSDKBackend()
    chunks = [chunk async for chunk in backend.generate_stream(_prompt())]
    assert len(chunks) == 2
    assert chunks[0].content == "hello world"
    assert chunks[0].is_final is False
    assert chunks[1].is_final is True


def test_text_prompt_skips_system_messages() -> None:
    backend = ClaudeAgentSDKBackend()
    prompt = LLMPrompt(
        system="ignored here",
        messages=[
            LLMMessage(role="system", content="should not appear"),
            LLMMessage(role="user", content="hello"),
            LLMMessage(role="assistant", content="hi"),
        ],
    )
    text = backend._build_text_prompt(prompt)
    assert "should not appear" not in text
    assert "User: hello" in text
    assert "Assistant: hi" in text


def test_model_name_property() -> None:
    backend = ClaudeAgentSDKBackend(model="stub-x")
    assert backend.model_name == "stub-x"
    assert ClaudeAgentSDKBackend().model_name == ""
