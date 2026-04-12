"""Google Gemini LLM backend implementation.

Wraps the google-genai Python SDK to provide an LLMBackend-compatible
interface for Gemini models.  Supports native function calling
(``function_call`` parts) and retry with exponential backoff.
"""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMChunk, LLMPrompt, LLMResponse, LLMUsage, ToolCall
from agenticapi.runtime.llm.retry import RetryConfig, with_retry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)


class GeminiBackend:
    """LLM backend using the Google Gemini API.

    Uses the google-genai SDK for async communication with the
    Gemini API. Supports both complete and streaming generation,
    native function calling, and automatic retry on transient errors.

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
        retry: RetryConfig | None = None,
    ) -> None:
        """Initialize the Gemini backend.

        Args:
            model: The Gemini model identifier to use.
            api_key: Google API key. Falls back to GOOGLE_API_KEY env var.
            max_tokens: Default maximum tokens for generation.
            timeout: API call timeout in seconds.
            retry: Optional retry configuration for transient failures.
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

        # Attempt to configure retryable exceptions from google SDK.
        retryable: tuple[type[Exception], ...] = ()
        try:
            from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable  # type: ignore[import-untyped]

            retryable = (ResourceExhausted, ServiceUnavailable)
        except ImportError:
            pass

        self._retry = retry if retry is not None else RetryConfig(max_retries=3, retryable_exceptions=retryable)

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
            response: Any = await with_retry(
                self._client.aio.models.generate_content,
                self._retry,
                model=self._model,
                contents=contents,
                config=config,
            )
            return self._build_response(response)

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

        config_kwargs: dict[str, Any] = {
            "system_instruction": prompt.system,
            "temperature": prompt.temperature,
            "max_output_tokens": prompt.max_tokens or self._max_tokens,
        }

        if prompt.tools:
            config_kwargs["tools"] = self._convert_tools(prompt.tools)

        if prompt.tool_choice is not None and prompt.tools:
            tool_config = self._convert_tool_choice(prompt.tool_choice)
            if tool_config is not None:
                config_kwargs["tool_config"] = tool_config

        config = types.GenerateContentConfig(**config_kwargs)

        contents: list[types.Content] = []
        for msg in prompt.messages:
            if msg.role == "system":
                continue
            role = "model" if msg.role == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg.content)]))

        return config, contents

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[Any]:
        """Convert framework tool definitions to Gemini format.

        Args:
            tools: Tool definitions in the framework's generic format.

        Returns:
            A list of Gemini Tool objects with function_declarations.
        """
        from google.genai import types

        declarations: list[types.FunctionDeclaration] = []
        for tool in tools:
            name = tool.get("name", "")
            description = tool.get("description", "")
            parameters = tool.get("parameters") or tool.get("input_schema") or {}

            declarations.append(
                types.FunctionDeclaration(
                    name=name,
                    description=description,
                    parameters=parameters if parameters else None,  # type: ignore[arg-type]
                )
            )

        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _convert_tool_choice(tool_choice: str | dict[str, str]) -> Any:
        """Convert framework tool_choice to Gemini tool_config.

        Args:
            tool_choice: The tool_choice value from LLMPrompt.

        Returns:
            A Gemini ToolConfig or None.
        """
        from google.genai import types

        if isinstance(tool_choice, dict):
            # Force a specific tool.
            return types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY",  # type: ignore[arg-type]
                    allowed_function_names=[tool_choice.get("name", "")],
                )
            )
        if tool_choice == "auto":
            return types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="AUTO"))  # type: ignore[arg-type]
        if tool_choice == "required":
            return types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY"))  # type: ignore[arg-type]
        if tool_choice == "none":
            return types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="NONE"))  # type: ignore[arg-type]
        return None

    def _build_response(self, response: Any) -> LLMResponse:
        """Build an LLMResponse from a Gemini response object.

        Extracts text content, function_call parts, finish_reason,
        and usage statistics.

        Args:
            response: The Gemini API response object.

        Returns:
            A fully populated LLMResponse.
        """
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        candidates = getattr(response, "candidates", None)
        if isinstance(candidates, list) and candidates:
            parts = getattr(candidates[0].content, "parts", None) or []
            for part in parts:
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    args = dict(fc.args) if fc.args else {}
                    tool_calls.append(
                        ToolCall(
                            id=str(uuid.uuid4()),
                            name=fc.name,
                            arguments=args,
                        )
                    )

        # Fallback: if candidates parsing didn't extract text, use
        # the convenience ``response.text`` property.
        if not text_parts and not tool_calls:
            fallback_text = getattr(response, "text", None)
            if fallback_text:
                text_parts.append(fallback_text)

        finish_reason: str | None = None
        if isinstance(candidates, list) and candidates:
            raw_reason = getattr(candidates[0], "finish_reason", None)
            if raw_reason is not None:
                reason_str = str(raw_reason)
                if "STOP" in reason_str:
                    finish_reason = "tool_calls" if tool_calls else "stop"
                elif "MAX_TOKENS" in reason_str:
                    finish_reason = "length"
                elif "SAFETY" in reason_str:
                    finish_reason = "content_filter"
                else:
                    finish_reason = "tool_calls" if tool_calls else "stop"

        usage_meta = getattr(response, "usage_metadata", None)
        usage = LLMUsage(
            input_tokens=(usage_meta.prompt_token_count or 0) if usage_meta else 0,
            output_tokens=(usage_meta.candidates_token_count or 0) if usage_meta else 0,
        )

        logger.info(
            "gemini_generate_complete",
            model=self._model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            tool_calls=len(tool_calls),
            finish_reason=finish_reason,
        )

        return LLMResponse(
            content="".join(text_parts),
            usage=usage,
            model=self._model,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
