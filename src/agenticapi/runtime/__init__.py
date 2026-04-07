"""Runtime layer for AgenticAPI.

Provides code generation, context management, LLM backends,
tool abstractions, and prompt templates.
"""

from __future__ import annotations

from agenticapi.runtime.code_generator import CodeGenerator, GeneratedCode
from agenticapi.runtime.context import AgentContext, ContextItem, ContextWindow
from agenticapi.runtime.llm import (
    AnthropicBackend,
    LLMBackend,
    LLMChunk,
    LLMMessage,
    LLMPrompt,
    LLMResponse,
    LLMUsage,
    MockBackend,
)
from agenticapi.runtime.prompts import build_code_generation_prompt, build_intent_parsing_prompt
from agenticapi.runtime.tools import DatabaseTool, Tool, ToolCapability, ToolDefinition, ToolRegistry

__all__ = [
    # Context
    "AgentContext",
    # LLM
    "AnthropicBackend",
    # Code generation
    "CodeGenerator",
    "ContextItem",
    "ContextWindow",
    # Tools
    "DatabaseTool",
    "GeneratedCode",
    "LLMBackend",
    "LLMChunk",
    "LLMMessage",
    "LLMPrompt",
    "LLMResponse",
    "LLMUsage",
    "MockBackend",
    "Tool",
    "ToolCapability",
    "ToolDefinition",
    "ToolRegistry",
    # Prompts
    "build_code_generation_prompt",
    "build_intent_parsing_prompt",
]
