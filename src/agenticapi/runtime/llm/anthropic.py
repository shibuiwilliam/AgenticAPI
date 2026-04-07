"""Anthropic LLM backend implementation.

Wraps the Anthropic Python SDK to provide an LLMBackend-compatible
interface for Claude models.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMChunk, LLMPrompt, LLMResponse, LLMUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)


class AnthropicBackend:
    """LLM backend using the Anthropic API (Claude models).

    Uses anthropic.AsyncAnthropic for async communication with the
    Anthropic API. Supports both complete and streaming generation.

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
    ) -> None:
        """Initialize the Anthropic backend.

        Args:
            model: The Anthropic model identifier to use.
            api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
            max_tokens: Default maximum tokens for generation.
            timeout: API call timeout in seconds.
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
            message = await self._client.messages.create(**kwargs)

            content = self._extract_content(message)
            usage = LLMUsage(
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
            )

            logger.info(
                "anthropic_generate_complete",
                model=self._model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

            return LLMResponse(
                content=content,
                usage=usage,
                model=message.model,
            )

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

        return kwargs

    @staticmethod
    def _extract_content(message: Any) -> str:
        """Extract text content from an Anthropic message response.

        Args:
            message: The Anthropic API message object.

        Returns:
            The concatenated text content from all content blocks.
        """
        parts: list[str] = []
        for block in message.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts)
