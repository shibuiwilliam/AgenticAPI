"""LLM backend abstractions and implementations.

Provides the LLMBackend protocol and concrete implementations
for Anthropic (Claude) and mock testing.
"""

from __future__ import annotations

from agenticapi.runtime.llm.anthropic import AnthropicBackend
from agenticapi.runtime.llm.base import (
    LLMBackend,
    LLMChunk,
    LLMMessage,
    LLMPrompt,
    LLMResponse,
    LLMUsage,
    ToolCall,
)
from agenticapi.runtime.llm.gemini import GeminiBackend
from agenticapi.runtime.llm.mock import MockBackend
from agenticapi.runtime.llm.openai import OpenAIBackend

__all__ = [
    "AnthropicBackend",
    "GeminiBackend",
    "LLMBackend",
    "LLMChunk",
    "LLMMessage",
    "LLMPrompt",
    "LLMResponse",
    "LLMUsage",
    "MockBackend",
    "OpenAIBackend",
    "ToolCall",
]
