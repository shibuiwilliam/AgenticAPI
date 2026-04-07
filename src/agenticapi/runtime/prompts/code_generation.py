"""Prompt building for code generation.

Constructs LLM prompts that instruct the model to generate safe
Python code using only the provided tools and context.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

if TYPE_CHECKING:
    from agenticapi.runtime.tools.base import ToolDefinition


def build_code_generation_prompt(
    intent_raw: str,
    intent_action: str,
    intent_domain: str,
    intent_parameters: dict[str, Any],
    tool_definitions: list[ToolDefinition],
    context: str,
) -> LLMPrompt:
    """Build an LLM prompt for code generation.

    Constructs a system prompt instructing the LLM to generate safe Python
    code using only the provided tools, and a user prompt from the intent.

    Args:
        intent_raw: The original natural language request.
        intent_action: The classified action type (read, write, etc.).
        intent_domain: The domain of the request (order, product, etc.).
        intent_parameters: Extracted parameters from the intent.
        tool_definitions: Available tools the generated code may use.
        context: Pre-assembled context string from the context window.

    Returns:
        An LLMPrompt ready to send to an LLM backend.
    """
    system = _build_system_prompt(tool_definitions)
    user = _build_user_prompt(intent_raw, intent_action, intent_domain, intent_parameters, context)
    return LLMPrompt(
        system=system,
        messages=[LLMMessage(role="user", content=user)],
        temperature=0.1,
    )


def _build_system_prompt(tool_definitions: list[ToolDefinition]) -> str:
    """Build the system prompt for code generation.

    Args:
        tool_definitions: Available tools the generated code may use.

    Returns:
        The system prompt string.
    """
    tool_descriptions = _format_tool_definitions(tool_definitions)

    return f"""\
You are a code generation agent for AgenticAPI. Your task is to generate safe, \
correct Python code that fulfills the user's intent using ONLY the provided tools.

## Rules

1. Generate ONLY Python code. No explanations outside of code comments.
2. Use ONLY the tools listed below. Do NOT import any modules.
3. Do NOT use `eval`, `exec`, `__import__`, `compile`, `getattr` with computed names, \
or any other dynamic code execution.
4. Do NOT access the filesystem, network, or environment variables.
5. Do NOT use infinite loops. All loops must have a clear termination condition.
6. The generated code must be a single async function named `execute` that accepts \
a `tools` parameter (a dictionary mapping tool names to async callables).
7. Return the result from the `execute` function.
8. Handle errors gracefully with try/except blocks.
9. Keep the code minimal and focused on the task.

## Available Tools

{tool_descriptions}

## Output Format

Wrap your code in a ```python code block. The code must define:

```python
async def execute(tools: dict) -> Any:
    # Your implementation here
    ...
```"""


def _build_user_prompt(
    intent_raw: str,
    intent_action: str,
    intent_domain: str,
    intent_parameters: dict[str, Any],
    context: str,
) -> str:
    """Build the user prompt from intent details.

    Args:
        intent_raw: The original natural language request.
        intent_action: The classified action type.
        intent_domain: The domain of the request.
        intent_parameters: Extracted parameters.
        context: Additional context string.

    Returns:
        The user prompt string.
    """
    # Escape user-supplied content to prevent XML tag injection
    safe_intent = html.escape(intent_raw)
    safe_action = html.escape(intent_action)
    safe_domain = html.escape(intent_domain)

    parts: list[str] = [
        f"<intent>\n{safe_intent}\n</intent>",
        f"<action>{safe_action}</action>",
        f"<domain>{safe_domain}</domain>",
    ]

    if intent_parameters:
        params_str = "\n".join(f"  {html.escape(str(k))}: {html.escape(str(v))}" for k, v in intent_parameters.items())
        parts.append(f"<parameters>\n{params_str}\n</parameters>")

    if context:
        parts.append(f"<context>\n{html.escape(context)}\n</context>")

    parts.append("Generate the Python code to fulfill this intent.")

    return "\n\n".join(parts)


def _format_tool_definitions(tool_definitions: list[ToolDefinition]) -> str:
    """Format tool definitions for inclusion in the system prompt.

    Args:
        tool_definitions: The tools to format.

    Returns:
        Formatted string describing each tool.
    """
    if not tool_definitions:
        return "No tools available."

    sections: list[str] = []
    for tool_def in tool_definitions:
        capabilities = ", ".join(c.value for c in tool_def.capabilities)
        section = f"### `{tool_def.name}`\n- Description: {tool_def.description}\n- Capabilities: {capabilities}"
        if tool_def.parameters_schema:
            params = tool_def.parameters_schema.get("properties", {})
            if params:
                param_lines = []
                for pname, pschema in params.items():
                    desc = pschema.get("description", "")
                    ptype = pschema.get("type", "any")
                    param_lines.append(f"  - `{pname}` ({ptype}): {desc}")
                section += "\n- Parameters:\n" + "\n".join(param_lines)
        sections.append(section)

    return "\n\n".join(sections)
