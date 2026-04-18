"""OpenAI LLM backend implementation.

Wraps the OpenAI Python SDK to provide an LLMBackend-compatible
interface for GPT models.  Supports native function calling
(``tool_calls`` on the assistant message) and retry with exponential
backoff.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMChunk, LLMPrompt, LLMResponse, LLMUsage, ToolCall
from agenticapi.runtime.llm.retry import RetryConfig, with_retry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)


class OpenAIBackend:
    """LLM backend using the OpenAI API (GPT models).

    Uses openai.AsyncOpenAI for async communication with the
    OpenAI API. Supports both complete and streaming generation,
    native function calling, and automatic retry on transient errors.

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
        retry: RetryConfig | None = None,
    ) -> None:
        """Initialize the OpenAI backend.

        Args:
            model: The OpenAI model identifier to use.
            api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
            max_tokens: Default maximum tokens for generation.
            timeout: API call timeout in seconds.
            retry: Optional retry configuration for transient failures.
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

        if retry is None:
            self._retry = RetryConfig(
                max_retries=3,
                retryable_exceptions=(
                    openai.RateLimitError,
                    openai.APITimeoutError,
                ),
            )
        else:
            self._retry = retry

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
            completion: Any = await with_retry(self._client.chat.completions.create, self._retry, **kwargs)
            return self._build_response(completion)

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

        Translates the framework's generic message and tool formats
        into the OpenAI-specific wire format:

        - Tool definitions are wrapped in ``{"type": "function",
          "function": {...}}``.
        - Assistant messages with ``tool_calls`` include a ``tool_calls``
          array of ``{"id", "type", "function": {"name", "arguments"}}``
          objects.
        - Tool-result messages (``role="tool"``) include ``tool_call_id``.

        Args:
            prompt: The LLM prompt to convert.

        Returns:
            Dictionary of keyword arguments for chat.completions.create().
        """
        messages: list[dict[str, Any]] = [{"role": "developer", "content": prompt.system}]
        for msg in prompt.messages:
            if msg.role == "system":
                continue
            if msg.role == "assistant" and msg.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
            elif msg.role == "tool" and msg.tool_call_id:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )
            else:
                messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_completion_tokens": prompt.max_tokens or self._max_tokens,
            "messages": messages,
            "temperature": prompt.temperature,
        }

        if prompt.tools:
            kwargs["tools"] = [self._normalize_tool(t) for t in prompt.tools]

        if prompt.tool_choice is not None and prompt.tools:
            kwargs["tool_choice"] = prompt.tool_choice

        return kwargs

    @staticmethod
    def _normalize_tool(t: dict[str, Any]) -> dict[str, Any]:
        """Normalize a tool definition to OpenAI format.

        Accepts both the framework's generic format
        (``{"name", "description", "parameters"}``) and the already-
        wrapped OpenAI format (``{"type": "function", "function": {...}}``).
        """
        if t.get("type") == "function" and "function" in t:
            return t
        return {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", t.get("input_schema", {})),
            },
        }

    def _build_response(self, completion: Any) -> LLMResponse:
        """Build an LLMResponse from an OpenAI completion object.

        Extracts text content, tool_calls, finish_reason, and usage.

        Args:
            completion: The OpenAI API completion object.

        Returns:
            A fully populated LLMResponse.
        """
        choice = completion.choices[0]
        content = choice.message.content or ""

        tool_calls: list[ToolCall] = []
        raw_calls = getattr(choice.message, "tool_calls", None)
        if raw_calls:
            for tc in raw_calls:
                try:
                    arguments = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=arguments,
                    )
                )

        finish_reason: str | None = None
        raw_reason = getattr(choice, "finish_reason", None)
        if raw_reason == "tool_calls":
            finish_reason = "tool_calls"
        elif raw_reason == "stop":
            finish_reason = "stop"
        elif raw_reason == "length":
            finish_reason = "length"
        elif raw_reason == "content_filter":
            finish_reason = "content_filter"
        elif raw_reason is not None:
            finish_reason = str(raw_reason)

        usage = LLMUsage(
            input_tokens=completion.usage.prompt_tokens if completion.usage else 0,
            output_tokens=completion.usage.completion_tokens if completion.usage else 0,
        )

        logger.info(
            "openai_generate_complete",
            model=self._model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            tool_calls=len(tool_calls),
            finish_reason=finish_reason,
        )

        return LLMResponse(
            content=content,
            usage=usage,
            model=completion.model or self._model,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
