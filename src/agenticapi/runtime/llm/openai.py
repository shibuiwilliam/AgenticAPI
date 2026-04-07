"""OpenAI LLM backend implementation.

Wraps the OpenAI Python SDK to provide an LLMBackend-compatible
interface for GPT models.
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


class OpenAIBackend:
    """LLM backend using the OpenAI API (GPT models).

    Uses openai.AsyncOpenAI for async communication with the
    OpenAI API. Supports both complete and streaming generation.

    Example:
        backend = OpenAIBackend(model="gpt-5.4-mini")
        response = await backend.generate(prompt)
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5.4-mini",
        api_key: str | None = None,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> None:
        """Initialize the OpenAI backend.

        Args:
            model: The OpenAI model identifier to use.
            api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
            max_tokens: Default maximum tokens for generation.
            timeout: API call timeout in seconds.
        """
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIBackend. Install it with: pip install openai"
            ) from exc

        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError("OpenAI API key must be provided via api_key parameter or OPENAI_API_KEY env var")

        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._client = openai.AsyncOpenAI(api_key=resolved_key, timeout=timeout)

    @property
    def model_name(self) -> str:
        """The name of the OpenAI model being used."""
        return self._model

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        """Send a prompt to the OpenAI API and return a complete response.

        Args:
            prompt: The LLM prompt to process.

        Returns:
            The complete LLM response with content and usage statistics.

        Raises:
            CodeGenerationError: If the API call fails.
        """
        try:
            kwargs = self._build_request_kwargs(prompt)
            completion = await self._client.chat.completions.create(**kwargs)

            content = completion.choices[0].message.content or ""
            usage = LLMUsage(
                input_tokens=completion.usage.prompt_tokens if completion.usage else 0,
                output_tokens=completion.usage.completion_tokens if completion.usage else 0,
            )

            logger.info(
                "openai_generate_complete",
                model=self._model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

            return LLMResponse(
                content=content,
                usage=usage,
                model=completion.model or self._model,
            )

        except Exception as exc:
            if isinstance(exc, CodeGenerationError):
                raise
            logger.error("openai_generate_failed", error=str(exc), model=self._model)
            raise CodeGenerationError(f"OpenAI API call failed: {exc}") from exc

    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
        """Stream a response from the OpenAI API.

        Args:
            prompt: The LLM prompt to process.

        Yields:
            LLMChunk objects as response tokens are generated.

        Raises:
            CodeGenerationError: If the API call fails.
        """
        try:
            kwargs = self._build_request_kwargs(prompt)
            kwargs["stream"] = True

            stream = await self._client.chat.completions.create(**kwargs)

            async for event in stream:
                if event.choices and event.choices[0].delta.content:
                    yield LLMChunk(content=event.choices[0].delta.content, is_final=False)

            yield LLMChunk(content="", is_final=True)

            logger.info("openai_stream_complete", model=self._model)

        except Exception as exc:
            if isinstance(exc, CodeGenerationError):
                raise
            logger.error("openai_stream_failed", error=str(exc), model=self._model)
            raise CodeGenerationError(f"OpenAI streaming API call failed: {exc}") from exc

    def _build_request_kwargs(self, prompt: LLMPrompt) -> dict[str, Any]:
        """Build keyword arguments for the OpenAI API call.

        Args:
            prompt: The LLM prompt to convert.

        Returns:
            Dictionary of keyword arguments for chat.completions.create().
        """
        messages: list[dict[str, str]] = [{"role": "developer", "content": prompt.system}]
        messages.extend({"role": msg.role, "content": msg.content} for msg in prompt.messages if msg.role != "system")

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": prompt.max_tokens or self._max_tokens,
            "messages": messages,
            "temperature": prompt.temperature,
        }

        if prompt.tools:
            kwargs["tools"] = prompt.tools

        return kwargs
