"""Anthropic LLM backend implementation.

Wraps the Anthropic Python SDK to provide an LLMBackend-compatible
interface for Claude models.  Supports native function calling
(``tool_use`` content blocks) and retry with exponential backoff.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMChunk, LLMPrompt, LLMResponse, LLMUsage, ToolCall
from agenticapi.runtime.llm.retry import RetryConfig, with_retry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)


class AnthropicBackend:
    """LLM backend using the Anthropic API (Claude models).

    Uses anthropic.AsyncAnthropic for async communication with the
    Anthropic API. Supports both complete and streaming generation,
    native function calling via ``tool_use`` content blocks, and
    automatic retry on transient errors.

    Example:
        backend = AnthropicBackend(model="claude-sonnet-4-6")
        response = await backend.generate(prompt)
    """

    def __init__(
        self,
        *,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        retry: RetryConfig | None = None,
    ) -> None:
        """Initialize the Anthropic backend.

        Args:
            model: The Anthropic model identifier to use.
            api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
            max_tokens: Default maximum tokens for generation.
            timeout: API call timeout in seconds.
            retry: Optional retry configuration for transient failures.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicBackend. Install it with: pip install anthropic"
            ) from exc

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError("Anthropic API key must be provided via api_key parameter or ANTHROPIC_API_KEY env var")

        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._client = anthropic.AsyncAnthropic(api_key=resolved_key, timeout=timeout)

        if retry is None:
            self._retry = RetryConfig(
                max_retries=3,
                retryable_exceptions=(
                    anthropic.RateLimitError,
                    anthropic.APITimeoutError,
                    anthropic.InternalServerError,
                ),
            )
        else:
            self._retry = retry

    @property
    def model_name(self) -> str:
        """The name of the Anthropic model being used."""
        return self._model

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        """Send a prompt to the Anthropic API and return a complete response.

        Args:
            prompt: The LLM prompt to process.

        Returns:
            The complete LLM response with content and usage statistics.

        Raises:
            CodeGenerationError: If the API call fails.
        """
        try:
            kwargs = self._build_request_kwargs(prompt)
            message: Any = await with_retry(self._client.messages.create, self._retry, **kwargs)
            return self._build_response(message)

        except Exception as exc:
            if isinstance(exc, CodeGenerationError):
                raise
            logger.error("anthropic_generate_failed", error=str(exc), model=self._model)
            raise CodeGenerationError(f"Anthropic API call failed: {exc}") from exc

    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
        """Stream a response from the Anthropic API.

        Args:
            prompt: The LLM prompt to process.

        Yields:
            LLMChunk objects as response tokens are generated.

        Raises:
            CodeGenerationError: If the API call fails.
        """
        try:
            kwargs = self._build_request_kwargs(prompt)

            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield LLMChunk(content=text, is_final=False)

            yield LLMChunk(content="", is_final=True)

            logger.info("anthropic_stream_complete", model=self._model)

        except Exception as exc:
            if isinstance(exc, CodeGenerationError):
                raise
            logger.error("anthropic_stream_failed", error=str(exc), model=self._model)
            raise CodeGenerationError(f"Anthropic streaming API call failed: {exc}") from exc

    def _build_request_kwargs(self, prompt: LLMPrompt) -> dict[str, Any]:
        """Build keyword arguments for the Anthropic API call.

        Args:
            prompt: The LLM prompt to convert.

        Returns:
            Dictionary of keyword arguments for messages.create().
        """
        messages = [{"role": msg.role, "content": msg.content} for msg in prompt.messages if msg.role != "system"]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": prompt.max_tokens or self._max_tokens,
            "system": prompt.system,
            "messages": messages,
            "temperature": prompt.temperature,
        }

        if prompt.tools:
            kwargs["tools"] = prompt.tools

        if prompt.tool_choice is not None and prompt.tools:
            if isinstance(prompt.tool_choice, dict):
                kwargs["tool_choice"] = prompt.tool_choice
            elif prompt.tool_choice == "auto":
                kwargs["tool_choice"] = {"type": "auto"}
            elif prompt.tool_choice == "required":
                kwargs["tool_choice"] = {"type": "any"}
            elif prompt.tool_choice == "none":
                # Anthropic doesn't have a "none" tool_choice — omit tools.
                kwargs.pop("tools", None)

        return kwargs

    def _build_response(self, message: Any) -> LLMResponse:
        """Build an LLMResponse from an Anthropic message object.

        Extracts text content, tool_use blocks, finish_reason, and
        usage statistics.

        Args:
            message: The Anthropic API message object.

        Returns:
            A fully populated LLMResponse.
        """
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in message.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
            elif getattr(block, "type", None) == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        finish_reason: str | None = None
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "tool_use":
            finish_reason = "tool_calls"
        elif stop_reason == "end_turn":
            finish_reason = "stop"
        elif stop_reason == "max_tokens":
            finish_reason = "length"
        elif stop_reason is not None:
            finish_reason = str(stop_reason)

        usage = LLMUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )

        logger.info(
            "anthropic_generate_complete",
            model=self._model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            tool_calls=len(tool_calls),
            finish_reason=finish_reason,
        )

        return LLMResponse(
            content="".join(text_parts),
            usage=usage,
            model=message.model,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
