"""LLM backend protocol and data classes.

Defines the Protocol for pluggable LLM backends and the data classes
used for prompts, responses, and streaming chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A single message in an LLM conversation.

    Attributes:
        role: The role of the message sender ("system", "user", or "assistant").
        content: The text content of the message.
    """

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class LLMPrompt:
    """A complete prompt to send to an LLM backend.

    Attributes:
        system: The system prompt instructing the LLM's behavior.
        messages: The conversation messages.
        tools: Optional tool definitions for function calling.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
    """

    system: str
    messages: list[LLMMessage]
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 4096
    temperature: float = 0.1


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Token usage information from an LLM call.

    Attributes:
        input_tokens: Number of tokens in the prompt.
        output_tokens: Number of tokens in the response.
    """

    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A complete response from an LLM backend.

    Attributes:
        content: The generated text content.
        reasoning: Optional chain-of-thought reasoning (if supported by model).
        confidence: Estimated confidence in the response (0.0-1.0).
        usage: Token usage statistics.
        model: The model identifier that generated this response.
    """

    content: str
    reasoning: str | None = None
    confidence: float = 1.0
    usage: LLMUsage = field(default_factory=lambda: LLMUsage(0, 0))
    model: str = ""


@dataclass(frozen=True, slots=True)
class LLMChunk:
    """A single chunk from a streaming LLM response.

    Attributes:
        content: The text content of this chunk.
        is_final: Whether this is the last chunk in the stream.
    """

    content: str
    is_final: bool = False


@runtime_checkable
class LLMBackend(Protocol):
    """Protocol for LLM backend implementations.

    Using Protocol (structural subtyping) so that third-party LLM wrapper
    libraries can be used without depending on AgenticAPI.
    """

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        """Send a prompt and receive a complete response.

        Args:
            prompt: The LLM prompt to process.

        Returns:
            The complete LLM response.
        """
        ...

    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
        """Send a prompt and receive a streaming response.

        Args:
            prompt: The LLM prompt to process.

        Yields:
            Chunks of the response as they are generated.
        """
        ...

    @property
    def model_name(self) -> str:
        """The name of the model being used."""
        ...
