"""Integration tests for GeminiBackend with a real API key.

Skipped automatically when ``GOOGLE_API_KEY`` is not set.
Run manually with::

    GOOGLE_API_KEY=... uv run pytest tests/integration/llm/test_real_gemini.py -v --timeout=60
"""

from __future__ import annotations

import os

import pytest

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set",
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


class TestGeminiRealToolCalls:
    """Verify tool calling works end-to-end with the real Gemini API."""

    async def test_tool_call_round_trip(self) -> None:
        """LLM should request the calculator tool for a math question."""
        from agenticapi.runtime.llm.gemini import GeminiBackend

        backend = GeminiBackend(api_key=os.environ["GOOGLE_API_KEY"])
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
        from agenticapi.runtime.llm.gemini import GeminiBackend

        backend = GeminiBackend(api_key=os.environ["GOOGLE_API_KEY"])

        # Turn 1
        r1 = await backend.generate(
            LLMPrompt(
                system="Use the calculator tool to answer math questions.",
                messages=[LLMMessage(role="user", content="What is 7 * 6?")],
                tools=[TOOL_DEF],
                tool_choice="required",
            )
        )
        assert r1.tool_calls

        # Turn 2
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
