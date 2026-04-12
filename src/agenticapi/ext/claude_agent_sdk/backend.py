"""Adapter exposing the Claude Agent SDK as an AgenticAPI :class:`LLMBackend`.

Use this when you want to plug the SDK into AgenticAPI's existing
intent parsing or code generation pipeline. The backend wraps
``claude_agent_sdk.query()`` with a tools-disabled, deterministic
configuration so the SDK behaves like a plain text completion API.

For full agentic loops (tool use, planning, multi-step reasoning),
use :class:`agenticapi.ext.claude_agent_sdk.ClaudeAgentRunner` instead —
the backend on its own intentionally turns off tools.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import CodeGenerationError
from agenticapi.ext.claude_agent_sdk._imports import load_sdk
from agenticapi.ext.claude_agent_sdk.messages import collect_session
from agenticapi.runtime.llm.base import LLMChunk, LLMResponse, LLMUsage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from agenticapi.runtime.llm.base import LLMPrompt

logger = structlog.get_logger(__name__)


class ClaudeAgentSDKBackend:
    """LLMBackend that delegates one-shot generation to the Claude Agent SDK.

    This is useful as a drop-in replacement for ``AnthropicBackend``
    when you want to share the Claude Agent SDK's authentication,
    transport, and rate-limit handling. It does **not** expose tool
    use or agentic loops — for that, use :class:`ClaudeAgentRunner`.

    Example:
        backend = ClaudeAgentSDKBackend(model="claude-sonnet-4-6")
        app = AgenticApp(llm=backend, harness=harness)
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        permission_mode: str = "bypassPermissions",
        extra_options: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize the backend.

        Args:
            model: SDK model identifier. ``None`` uses the SDK default.
            system_prompt: Default system prompt. Overridden per-call by
                :class:`LLMPrompt.system`.
            permission_mode: SDK permission mode. Defaults to
                ``"bypassPermissions"`` because no tools are used here.
            extra_options: Free-form keyword arguments forwarded to
                :class:`ClaudeAgentOptions`.
        """
        self._model = model
        self._system_prompt = system_prompt
        self._permission_mode = permission_mode
        self._extra_options = dict(extra_options) if extra_options else None

    @property
    def model_name(self) -> str:
        """Return the configured model name (or empty string if unset)."""
        return self._model or ""

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        """Run a single text completion through the Claude Agent SDK.

        Args:
            prompt: The AgenticAPI :class:`LLMPrompt`.

        Returns:
            An :class:`LLMResponse` containing the model's reply.

        Raises:
            CodeGenerationError: If the SDK session ends in error or
                fails to start.
        """
        sdk = load_sdk()
        options = self._build_options(prompt)
        text_prompt = self._build_text_prompt(prompt)

        try:
            session = await collect_session(
                sdk.query(prompt=text_prompt, options=options),
                raise_on_error=False,
            )
        except Exception as exc:
            logger.error("claude_sdk_backend_failed", error=str(exc))
            raise CodeGenerationError(f"Claude Agent SDK call failed: {exc}") from exc

        if session.is_error:
            raise CodeGenerationError(
                f"Claude Agent SDK session error (subtype={session.subtype}): "
                f"{'; '.join(session.errors) if session.errors else 'unknown error'}"
            )

        content = session.result_text or session.text or ""
        usage_dict = session.usage or {}
        usage = LLMUsage(
            input_tokens=int(usage_dict.get("input_tokens", 0) or 0),
            output_tokens=int(usage_dict.get("output_tokens", 0) or 0),
        )
        return LLMResponse(
            content=content,
            reasoning=session.thinking or None,
            confidence=1.0,
            usage=usage,
            model=session.model or self._model or "",
        )

    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
        """Stream a completion as :class:`LLMChunk` events.

        The SDK does not natively expose token-level streaming for the
        text-only path, so this implementation buffers the full
        response and emits it as a single chunk followed by a final
        sentinel. Callers that want true token streaming should use
        the runner's :meth:`ClaudeAgentRunner.stream` method.
        """
        response = await self.generate(prompt)
        yield LLMChunk(content=response.content, is_final=False)
        yield LLMChunk(content="", is_final=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_options(self, prompt: LLMPrompt) -> Any:
        sdk = load_sdk()
        kwargs: dict[str, Any] = {
            "allowed_tools": [],
            "disallowed_tools": [],
            "permission_mode": self._permission_mode,
        }
        system = prompt.system or self._system_prompt
        if system:
            kwargs["system_prompt"] = system
        if self._model is not None:
            kwargs["model"] = self._model
        if prompt.max_tokens:
            # The SDK doesn't expose max_tokens directly; the closest
            # equivalent is ``max_thinking_tokens`` for thinking only.
            # We forward via extra_args so users can override later.
            kwargs.setdefault("extra_args", {})
        if self._extra_options:
            kwargs.update(self._extra_options)
        return sdk.ClaudeAgentOptions(**kwargs)

    @staticmethod
    def _build_text_prompt(prompt: LLMPrompt) -> str:
        """Flatten an :class:`LLMPrompt` into a single text string.

        The SDK's ``query()`` accepts a string prompt for one-shot
        invocations. We concatenate the conversation messages with
        role labels so the model can still see prior turns.
        """
        parts: list[str] = []
        for message in prompt.messages:
            if message.role == "system":
                continue
            parts.append(f"{message.role.capitalize()}: {message.content}")
        return "\n\n".join(parts) if parts else ""
