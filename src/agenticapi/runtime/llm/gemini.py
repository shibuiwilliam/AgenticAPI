"""Google Gemini LLM backend implementation.

Wraps the google-genai Python SDK to provide an LLMBackend-compatible
interface for Gemini models.
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


class GeminiBackend:
    """LLM backend using the Google Gemini API.

    Uses the google-genai SDK for async communication with the
    Gemini API. Supports both complete and streaming generation.

    Example:
        backend = GeminiBackend(model="gemini-2.5-flash")
        response = await backend.generate(prompt)
    """

    def __init__(
        self,
        *,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> None:
        """Initialize the Gemini backend.

        Args:
            model: The Gemini model identifier to use.
            api_key: Google API key. Falls back to GOOGLE_API_KEY env var.
            max_tokens: Default maximum tokens for generation.
            timeout: API call timeout in seconds.
        """
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "The 'google-genai' package is required for GeminiBackend. Install it with: pip install google-genai"
            ) from exc

        resolved_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not resolved_key:
            raise ValueError("Google API key must be provided via api_key parameter or GOOGLE_API_KEY env var")

        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._client = genai.Client(api_key=resolved_key)

    @property
    def model_name(self) -> str:
        """The name of the Gemini model being used."""
        return self._model

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        """Send a prompt to the Gemini API and return a complete response.

        Args:
            prompt: The LLM prompt to process.

        Returns:
            The complete LLM response with content and usage statistics.

        Raises:
            CodeGenerationError: If the API call fails.
        """
        try:
            config, contents = self._build_request_params(prompt)
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )

            content = response.text or ""
            usage_meta = response.usage_metadata
            usage = LLMUsage(
                input_tokens=(usage_meta.prompt_token_count or 0) if usage_meta else 0,
                output_tokens=(usage_meta.candidates_token_count or 0) if usage_meta else 0,
            )

            logger.info(
                "gemini_generate_complete",
                model=self._model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

            return LLMResponse(
                content=content,
                usage=usage,
                model=self._model,
            )

        except Exception as exc:
            if isinstance(exc, CodeGenerationError):
                raise
            logger.error("gemini_generate_failed", error=str(exc), model=self._model)
            raise CodeGenerationError(f"Gemini API call failed: {exc}") from exc

    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
        """Stream a response from the Gemini API.

        Args:
            prompt: The LLM prompt to process.

        Yields:
            LLMChunk objects as response tokens are generated.

        Raises:
            CodeGenerationError: If the API call fails.
        """
        try:
            config, contents = self._build_request_params(prompt)

            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=contents,
                config=config,
            )
            async for chunk in stream:
                if chunk.text:
                    yield LLMChunk(content=chunk.text, is_final=False)

            yield LLMChunk(content="", is_final=True)

            logger.info("gemini_stream_complete", model=self._model)

        except Exception as exc:
            if isinstance(exc, CodeGenerationError):
                raise
            logger.error("gemini_stream_failed", error=str(exc), model=self._model)
            raise CodeGenerationError(f"Gemini streaming API call failed: {exc}") from exc

    def _build_request_params(self, prompt: LLMPrompt) -> tuple[Any, list[Any]]:
        """Build request parameters for the Gemini API call.

        Args:
            prompt: The LLM prompt to convert.

        Returns:
            A tuple of (GenerateContentConfig, contents list).
        """
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=prompt.system,
            temperature=prompt.temperature,
            max_output_tokens=prompt.max_tokens or self._max_tokens,
        )

        contents: list[types.Content] = []
        for msg in prompt.messages:
            if msg.role == "system":
                continue
            role = "model" if msg.role == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg.content)]))

        return config, contents
