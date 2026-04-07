"""Tests for MockSandbox and mock_llm."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import SandboxViolation
from agenticapi.testing.mocks import MockSandbox, mock_llm


class TestMockLlm:
    def test_yields_mock_backend(self) -> None:
        with mock_llm(responses=["hello"]) as backend:
            assert backend.model_name == "mock"

    async def test_backend_returns_responses(self) -> None:
        from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

        prompt = LLMPrompt(system="sys", messages=[LLMMessage(role="user", content="hi")])
        with mock_llm(responses=["resp1", "resp2"]) as backend:
            r1 = await backend.generate(prompt)
            r2 = await backend.generate(prompt)
            assert r1.content == "resp1"
            assert r2.content == "resp2"


class TestMockSandbox:
    async def test_allowed_result_matches(self) -> None:
        sandbox = MockSandbox(allowed_results={"SELECT COUNT(*)": [{"count": 42}]})
        async with sandbox as sb:
            result = await sb.execute("SELECT COUNT(*) FROM orders")
            assert result.return_value == [{"count": 42}]
            assert result.output == [{"count": 42}]

    async def test_denied_operation_raises(self) -> None:
        sandbox = MockSandbox(denied_operations=["DROP TABLE"])
        async with sandbox as sb:
            with pytest.raises(SandboxViolation, match="DROP TABLE"):
                await sb.execute("DROP TABLE users")

    async def test_default_result_when_no_match(self) -> None:
        sandbox = MockSandbox()
        async with sandbox as sb:
            result = await sb.execute("some code")
            assert result.return_value is None
            assert result.output is None

    async def test_execution_count(self) -> None:
        sandbox = MockSandbox()
        assert sandbox.execution_count == 0
        async with sandbox as sb:
            await sb.execute("a")
            await sb.execute("b")
        assert sandbox.execution_count == 2

    async def test_denied_checked_before_allowed(self) -> None:
        sandbox = MockSandbox(
            allowed_results={"DROP TABLE": "should not match"},
            denied_operations=["DROP TABLE"],
        )
        async with sandbox as sb:
            with pytest.raises(SandboxViolation):
                await sb.execute("DROP TABLE users")

    async def test_context_manager(self) -> None:
        sandbox = MockSandbox()
        async with sandbox as sb:
            assert sb is sandbox
