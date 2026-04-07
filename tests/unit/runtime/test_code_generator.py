"""Tests for CodeGenerator."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.code_generator import CodeGenerator, _extract_code
from agenticapi.runtime.context import AgentContext
from agenticapi.runtime.llm.mock import MockBackend


class TestExtractCode:
    def test_extract_from_python_block(self) -> None:
        llm_output = "Here is the code:\n```python\nresult = 42\n```\nDone."
        code = _extract_code(llm_output)
        assert code == "result = 42"

    def test_extract_from_plain_block(self) -> None:
        llm_output = "```python\nx = 1\ny = 2\n```"
        code = _extract_code(llm_output)
        assert "x = 1" in code
        assert "y = 2" in code

    def test_no_code_block_returns_raw(self) -> None:
        llm_output = "result = 42"
        code = _extract_code(llm_output)
        assert code == "result = 42"

    def test_multiple_blocks_returns_first(self) -> None:
        llm_output = "```python\nx = 1\n```\n```python\nresult = 1\nresult += 1\n```"
        code = _extract_code(llm_output)
        assert code == "x = 1"

    def test_strips_whitespace(self) -> None:
        llm_output = "  result = 42  "
        code = _extract_code(llm_output)
        assert code == "result = 42"


class TestCodeGeneratorGenerate:
    async def test_generate_returns_generated_code(self) -> None:
        backend = MockBackend(responses=["```python\nresult = 42\n```"])
        generator = CodeGenerator(llm=backend)
        context = AgentContext(trace_id="test-trace", endpoint_name="orders")

        result = await generator.generate(
            intent_raw="show count",
            intent_action="read",
            intent_domain="order",
            intent_parameters={},
            context=context,
        )

        assert result.code == "result = 42"
        assert result.usage is not None

    async def test_generate_empty_code_raises(self) -> None:
        backend = MockBackend(responses=[""])
        generator = CodeGenerator(llm=backend)
        context = AgentContext(trace_id="test-trace", endpoint_name="orders")

        with pytest.raises(CodeGenerationError, match="empty"):
            await generator.generate(
                intent_raw="test",
                intent_action="read",
                intent_domain="general",
                intent_parameters={},
                context=context,
            )

    async def test_generate_llm_failure_raises(self) -> None:
        backend = MockBackend()  # No responses -> will raise
        generator = CodeGenerator(llm=backend)
        context = AgentContext(trace_id="test-trace", endpoint_name="orders")

        with pytest.raises(CodeGenerationError):
            await generator.generate(
                intent_raw="test",
                intent_action="read",
                intent_domain="general",
                intent_parameters={},
                context=context,
            )

    async def test_generate_plain_code_no_block(self) -> None:
        backend = MockBackend(responses=["result = [1, 2, 3]"])
        generator = CodeGenerator(llm=backend)
        context = AgentContext(trace_id="test-trace", endpoint_name="orders")

        result = await generator.generate(
            intent_raw="get items",
            intent_action="read",
            intent_domain="order",
            intent_parameters={},
            context=context,
        )

        assert result.code == "result = [1, 2, 3]"
