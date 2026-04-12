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
        response_schema: Optional JSON Schema (Pydantic-derived) the
            LLM must conform to. Backends translate this into the
            provider's native structured-output API
            (Anthropic ``tools`` + ``tool_choice``, OpenAI
            ``response_format=json_schema``, Gemini ``response_schema``).
            When ``None``, the model produces free-form text as before.
        response_schema_name: Optional descriptive name for the
            schema, used by some providers as the schema title.
        tool_choice: Controls how the model selects tools. Accepted
            values: ``"auto"`` (model decides), ``"required"`` (must
            call a tool), ``"none"`` (never call a tool), or a dict
            ``{"type": "tool", "name": "..."}`` to force a specific
            tool. ``None`` (default) defers to the provider's default.
    """

    system: str
    messages: list[LLMMessage]
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 4096
    temperature: float = 0.1
    response_schema: dict[str, Any] | None = None
    response_schema_name: str | None = None
    tool_choice: str | dict[str, str] | None = None


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
class ToolCall:
    """A single native function-call request from an LLM (Phase E3).

    Modern LLM APIs (Anthropic ``tools``/``tool_choice``, OpenAI
    ``tools``, Gemini ``function_declarations``) emit structured
    function-call objects when they want a tool invoked instead of
    producing free-form Python code. This dataclass is the
    framework-agnostic representation of one such call.

    The ``LLMBackend`` protocol promises to populate
    :attr:`LLMResponse.tool_calls` with one entry per requested
    invocation. Downstream consumers (the harness's tool-first path
    in Phase E4) iterate the list, validate the arguments against
    the registered tool's Pydantic schema, and dispatch to the tool
    with cost / latency / reliability all dramatically better than
    going through code generation + sandbox execution.

    Attributes:
        id: Provider-supplied identifier for this call. Echoed back
            in the tool result so multi-call exchanges stay in sync.
        name: The tool name the model wants to invoke. Resolved
            against the registered :class:`ToolRegistry`.
        arguments: The keyword arguments the model produced for the
            tool. Always a dict; the framework validates it through
            the tool's Pydantic input model before dispatching.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A complete response from an LLM backend.

    Attributes:
        content: The generated text content. Empty string when the
            response was a pure tool-call (no narrative text).
        reasoning: Optional chain-of-thought reasoning (if supported by model).
        confidence: Estimated confidence in the response (0.0-1.0).
        usage: Token usage statistics.
        model: The model identifier that generated this response.
        tool_calls: Phase E3 — native function-call requests from the
            model. Empty list when the model produced text instead of
            (or in addition to) calling a tool. Populated by every
            backend that supports function calling: Anthropic, OpenAI,
            Gemini, Mock.
        finish_reason: Why the model stopped generating. One of
            ``"stop"``, ``"length"``, ``"tool_calls"``, ``"content_filter"``,
            or backend-specific values. ``None`` for backends that
            don't expose this.
    """

    content: str
    reasoning: str | None = None
    confidence: float = 1.0
    usage: LLMUsage = field(default_factory=lambda: LLMUsage(0, 0))
    model: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None


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
