"""Integration tests for AnthropicBackend with a real API key.

Skipped automatically when ``ANTHROPIC_API_KEY`` is not set.
Run manually with::

    ANTHROPIC_API_KEY=sk-... uv run pytest tests/integration/llm/test_real_anthropic.py -v --timeout=60
"""

from __future__ import annotations

import os

import pytest

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)

TOOL_DEF = {
    "name": "calculator",
    "description": "Evaluate a math expression and return the numeric result",
    "parameters": {
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "Math expression to evaluate"}},
        "required": ["expression"],
    },
}


class TestAnthropicRealToolCalls:
    """Verify tool calling works end-to-end with the real Anthropic API."""

    async def test_tool_call_round_trip(self) -> None:
        """LLM should request the calculator tool for a math question."""
        from agenticapi.runtime.llm.anthropic import AnthropicBackend

        backend = AnthropicBackend(api_key=os.environ["ANTHROPIC_API_KEY"])
        prompt = LLMPrompt(
            system="Use the calculator tool to answer math questions. Always use the tool.",
            messages=[LLMMessage(role="user", content="What is 7 * 6?")],
            tools=[TOOL_DEF],
            tool_choice="required",
        )
        r = await backend.generate(prompt)
        assert r.tool_calls, f"Expected tool_calls, got finish_reason={r.finish_reason}"
        assert r.tool_calls[0].name == "calculator"
        assert r.finish_reason == "tool_calls"

    async def test_multi_turn_with_tool_result(self) -> None:
        """LLM should produce a final answer after receiving the tool result."""
        from agenticapi.runtime.llm.anthropic import AnthropicBackend

        backend = AnthropicBackend(api_key=os.environ["ANTHROPIC_API_KEY"])

        # Turn 1: ask a question
        r1 = await backend.generate(
            LLMPrompt(
                system="Use the calculator tool to answer math questions.",
                messages=[LLMMessage(role="user", content="What is 7 * 6?")],
                tools=[TOOL_DEF],
                tool_choice="required",
            )
        )
        assert r1.tool_calls

        # Turn 2: send the tool result back
        r2 = await backend.generate(
            LLMPrompt(
                system="Use the calculator tool to answer math questions.",
                messages=[
                    LLMMessage(role="user", content="What is 7 * 6?"),
                    LLMMessage(role="assistant", content="", tool_calls=list(r1.tool_calls)),
                    LLMMessage(role="tool", content='{"result": 42}', tool_call_id=r1.tool_calls[0].id),
                ],
                tools=[TOOL_DEF],
            )
        )
        assert r2.finish_reason == "stop"
        assert "42" in r2.content
