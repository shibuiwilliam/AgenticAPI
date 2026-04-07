"""Code generation engine.

Generates Python code from natural language intents using an LLM backend.
The generated code is validated and structured for downstream harness evaluation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.prompts.code_generation import build_code_generation_prompt
from agenticapi.runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext
    from agenticapi.runtime.llm.base import LLMBackend, LLMUsage

logger = structlog.get_logger(__name__)

# Regex to extract Python code blocks from LLM output
_CODE_BLOCK_PATTERN = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True, slots=True)
class GeneratedCode:
    """Result of code generation.

    Attributes:
        code: The generated Python source code.
        reasoning: Optional chain-of-thought reasoning from the LLM.
        confidence: LLM's confidence in the generated code (0.0-1.0).
        usage: Token usage statistics from the LLM call.
    """

    code: str
    reasoning: str | None = None
    confidence: float = 1.0
    usage: LLMUsage | None = None


class CodeGenerator:
    """Generates Python code from intents using an LLM backend.

    Uses the LLM to convert natural language intents into executable
    Python code, scoped to the available tools. The generated code
    is extracted from the LLM response and returned for harness evaluation.

    Example:
        generator = CodeGenerator(llm=backend, tools=registry)
        result = await generator.generate(
            intent_raw="Show me order count",
            intent_action="read",
            intent_domain="order",
            intent_parameters={},
            context=agent_context,
        )
        print(result.code)
    """

    def __init__(
        self,
        *,
        llm: LLMBackend,
        tools: ToolRegistry | None = None,
    ) -> None:
        """Initialize the code generator.

        Args:
            llm: The LLM backend to use for code generation.
            tools: Optional tool registry defining available tools.
        """
        self._llm = llm
        self._tools = tools or ToolRegistry()

    async def generate(
        self,
        *,
        intent_raw: str,
        intent_action: str,
        intent_domain: str,
        intent_parameters: dict[str, Any],
        context: AgentContext,
        sandbox_data: dict[str, object] | None = None,
    ) -> GeneratedCode:
        """Generate Python code from an intent.

        Builds a prompt from the intent and context, sends it to the LLM,
        and extracts the generated code from the response.

        Args:
            intent_raw: The original natural language request.
            intent_action: The classified action type.
            intent_domain: The domain of the request.
            intent_parameters: Extracted parameters from the intent.
            context: The agent execution context.
            sandbox_data: Pre-fetched tool data to include in the prompt
                so the LLM knows the data schema.

        Returns:
            GeneratedCode containing the extracted code and metadata.

        Raises:
            CodeGenerationError: If code generation or extraction fails.
        """
        tool_definitions = self._tools.get_definitions()
        context_str = context.context_window.build()

        prompt = build_code_generation_prompt(
            intent_raw=intent_raw,
            intent_action=intent_action,
            intent_domain=intent_domain,
            intent_parameters=intent_parameters,
            tool_definitions=tool_definitions,
            context=context_str,
            sandbox_data=sandbox_data,
        )

        logger.info(
            "code_generation_started",
            trace_id=context.trace_id,
            intent_action=intent_action,
            intent_domain=intent_domain,
            tool_count=len(tool_definitions),
        )

        try:
            response = await self._llm.generate(prompt)
        except CodeGenerationError:
            raise
        except Exception as exc:
            logger.error("code_generation_llm_failed", trace_id=context.trace_id, error=str(exc))
            raise CodeGenerationError(f"LLM call failed during code generation: {exc}") from exc

        code = _extract_code(response.content or "")
        if not code.strip():
            logger.error(
                "code_generation_empty", trace_id=context.trace_id, raw_response=(response.content or "")[:200]
            )
            raise CodeGenerationError("LLM returned empty code")

        logger.info(
            "code_generation_complete",
            trace_id=context.trace_id,
            code_lines=code.count("\n") + 1,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        return GeneratedCode(
            code=code,
            reasoning=response.reasoning,
            confidence=response.confidence,
            usage=response.usage,
        )


def _extract_code(llm_output: str) -> str:
    """Extract Python code from LLM output.

    Looks for ```python code blocks first. If none found, treats
    the entire output as code.

    Args:
        llm_output: The raw LLM response text.

    Returns:
        The extracted Python code string.
    """
    matches: list[str] = _CODE_BLOCK_PATTERN.findall(llm_output)
    if matches:
        # Return the first code block (most likely the main implementation)
        return matches[0].strip()

    # No code block markers found; use the entire output
    return llm_output.strip()
