"""Adapt Claude Agent SDK message streams into AgenticAPI responses.

The SDK ``query()`` async iterator yields a heterogeneous stream:

* ``SystemMessage`` — session init, MCP server status, available tools.
* ``UserMessage`` — echo of the user's prompt and tool results.
* ``AssistantMessage`` — model output, made up of ``TextBlock``,
  ``ThinkingBlock``, ``ToolUseBlock``, ``ToolResultBlock``.
* ``ResultMessage`` — final answer + cost/usage/duration.
* ``StreamEvent`` / ``RateLimitEvent`` — partial deltas and rate limit
  notifications (only when ``include_partial_messages=True``).

This module collects that stream into an :class:`AgentSessionResult`
that the runner converts to an AgenticAPI :class:`AgentResponse`.

The collector is intentionally permissive: each block is examined by
``getattr`` so the adapter doesn't break when the SDK adds new optional
fields. Anything we don't recognise is silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from agenticapi.interface.response import AgentResponse

from agenticapi_claude_agent_sdk.exceptions import ClaudeAgentSDKRunError

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class ToolCallRecord:
    """A single tool call observed in the SDK message stream.

    Attributes:
        tool_use_id: SDK identifier for the tool call.
        name: Tool name (e.g. ``Read``, ``mcp__agenticapi__db``).
        input: The arguments the model passed to the tool.
        result: The tool's response, if observed.
        is_error: Whether the tool result was an error.
    """

    tool_use_id: str
    name: str
    input: dict[str, Any]
    result: Any = None
    is_error: bool | None = None


@dataclass(slots=True)
class AgentSessionEvent:
    """A streamable event for the runner's ``stream()`` API.

    Attributes:
        kind: One of ``"text"``, ``"thinking"``, ``"tool_use"``,
            ``"tool_result"``, ``"system"``, ``"result"``, ``"error"``.
        payload: A small JSON-serialisable dict describing the event.
    """

    kind: str
    payload: dict[str, Any]


@dataclass(slots=True)
class AgentSessionResult:
    """Aggregated result of a Claude Agent SDK session.

    Constructed by :func:`collect_session`. Convert to an
    AgenticAPI :class:`AgentResponse` via :meth:`to_agent_response`.

    Attributes:
        text: Concatenated assistant text blocks (the visible reply).
        thinking: Concatenated extended-thinking blocks, when enabled.
        tool_calls: All tool calls observed during the session.
        result_text: ``ResultMessage.result`` if present.
        structured_output: ``ResultMessage.structured_output`` if present.
        session_id: Session ID returned by the SDK.
        model: Model name reported by the assistant messages.
        is_error: Whether the run ended in error.
        subtype: ``ResultMessage.subtype`` for diagnostics.
        duration_ms: Wall-clock duration reported by the SDK.
        total_cost_usd: Cost reported by the SDK, if any.
        usage: Token usage dict from the SDK.
        num_turns: Number of agentic turns the SDK executed.
        errors: Error strings from ``ResultMessage.errors``.
    """

    text: str = ""
    thinking: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    result_text: str | None = None
    structured_output: Any = None
    session_id: str | None = None
    model: str | None = None
    is_error: bool = False
    subtype: str | None = None
    duration_ms: int | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    num_turns: int | None = None
    errors: list[str] = field(default_factory=list)

    def to_agent_response(
        self,
        *,
        execution_trace_id: str | None = None,
    ) -> AgentResponse:
        """Build an AgenticAPI :class:`AgentResponse` from the session."""
        result_payload: Any
        if self.structured_output is not None:
            result_payload = self.structured_output
        elif self.result_text is not None:
            result_payload = self.result_text
        else:
            result_payload = self.text or None

        # ``generated_code`` collects all source-bearing tool inputs
        # so that audit/UI layers can show "what code did the agent
        # actually run". This mirrors the harness's ExecutionTrace.
        code_snippets: list[str] = []
        for call in self.tool_calls:
            for source_field in ("command", "content", "new_string"):
                if source_field in call.input:
                    code_snippets.append(f"# tool={call.name} field={source_field}\n{call.input[source_field]}")
                    break
        generated_code = "\n\n".join(code_snippets) if code_snippets else None

        confidence = 0.0 if self.is_error else 1.0
        status = "error" if self.is_error else "completed"

        return AgentResponse(
            result=result_payload,
            status=status,
            generated_code=generated_code,
            reasoning=self.thinking or None,
            confidence=confidence,
            execution_trace_id=execution_trace_id,
            error="; ".join(self.errors) if self.errors else None,
        )


def _block_kind(block: Any) -> str:
    """Best-effort dispatch on a content block's runtime type name."""
    return type(block).__name__


def _extract_text_blocks(content: Any) -> tuple[list[str], list[str], list[ToolCallRecord]]:
    """Pull text, thinking, and tool-use info out of a content block list."""
    texts: list[str] = []
    thinking: list[str] = []
    tool_uses: list[ToolCallRecord] = []
    if not isinstance(content, list):
        return texts, thinking, tool_uses
    for block in content:
        kind = _block_kind(block)
        if kind == "TextBlock":
            text_value = getattr(block, "text", None)
            if text_value:
                texts.append(text_value)
        elif kind == "ThinkingBlock":
            thinking_value = getattr(block, "thinking", None)
            if thinking_value:
                thinking.append(thinking_value)
        elif kind == "ToolUseBlock":
            tool_uses.append(
                ToolCallRecord(
                    tool_use_id=getattr(block, "id", "") or "",
                    name=getattr(block, "name", "") or "",
                    input=dict(getattr(block, "input", {}) or {}),
                )
            )
        elif kind == "ToolResultBlock":
            # Tool results appear in user messages; we still attach them
            # to the matching tool call by id when we encounter them.
            pass
    return texts, thinking, tool_uses


def _attach_tool_results(content: Any, tool_calls_by_id: dict[str, ToolCallRecord]) -> None:
    """Attach ToolResult content to the matching ToolCallRecord."""
    if not isinstance(content, list):
        return
    for block in content:
        if _block_kind(block) != "ToolResultBlock":
            continue
        tool_use_id = getattr(block, "tool_use_id", "") or ""
        record = tool_calls_by_id.get(tool_use_id)
        if record is None:
            continue
        record.result = getattr(block, "content", None)
        record.is_error = getattr(block, "is_error", None)


async def collect_session(
    messages: AsyncIterable[Any],
    *,
    raise_on_error: bool = True,
) -> AgentSessionResult:
    """Drain an SDK message stream into an :class:`AgentSessionResult`.

    Args:
        messages: The async iterable returned by ``claude_agent_sdk.query()``.
        raise_on_error: When True (default), raise
            :class:`ClaudeAgentSDKRunError` if the run ends with
            ``ResultMessage.is_error == True``.

    Returns:
        The aggregated session result.

    Raises:
        ClaudeAgentSDKRunError: When ``raise_on_error`` is True and the
            session ended in error.
    """
    result = AgentSessionResult()
    tool_calls_by_id: dict[str, ToolCallRecord] = {}

    async for message in messages:
        message_kind = type(message).__name__

        if message_kind == "SystemMessage":
            data = getattr(message, "data", {}) or {}
            if "session_id" in data and not result.session_id:
                result.session_id = str(data["session_id"])
            continue

        if message_kind == "AssistantMessage":
            content = getattr(message, "content", None)
            texts, thinking, tool_uses = _extract_text_blocks(content)
            if texts:
                result.text += ("\n" if result.text else "") + "\n".join(texts)
            if thinking:
                result.thinking += ("\n" if result.thinking else "") + "\n".join(thinking)
            for record in tool_uses:
                tool_calls_by_id[record.tool_use_id] = record
                result.tool_calls.append(record)
            model = getattr(message, "model", None)
            if model:
                result.model = model
            continue

        if message_kind == "UserMessage":
            content = getattr(message, "content", None)
            _attach_tool_results(content, tool_calls_by_id)
            continue

        if message_kind == "ResultMessage":
            result.result_text = getattr(message, "result", None)
            result.structured_output = getattr(message, "structured_output", None)
            result.session_id = getattr(message, "session_id", result.session_id)
            result.is_error = bool(getattr(message, "is_error", False))
            result.subtype = getattr(message, "subtype", None)
            result.duration_ms = getattr(message, "duration_ms", None)
            result.total_cost_usd = getattr(message, "total_cost_usd", None)
            result.usage = getattr(message, "usage", None)
            result.num_turns = getattr(message, "num_turns", None)
            sdk_errors = getattr(message, "errors", None) or []
            result.errors = [str(e) for e in sdk_errors]
            break

    if raise_on_error and result.is_error:
        raise ClaudeAgentSDKRunError(
            f"Claude Agent SDK session ended with error (subtype={result.subtype})",
            subtype=result.subtype,
            session_id=result.session_id,
            errors=result.errors,
        )

    return result


async def stream_session_events(messages: AsyncIterable[Any]) -> AsyncIterator[AgentSessionEvent]:
    """Adapt the SDK's message stream into a flat ``AgentSessionEvent`` stream.

    Useful for callers that want to surface events to a UI or to a
    Server-Sent-Events response, without waiting for the whole session
    to finish.
    """
    async for message in messages:
        message_kind = type(message).__name__
        if message_kind == "SystemMessage":
            yield AgentSessionEvent(kind="system", payload={"data": getattr(message, "data", {}) or {}})
            continue
        if message_kind == "AssistantMessage":
            content = getattr(message, "content", None)
            texts, thinking, tool_uses = _extract_text_blocks(content)
            for text in texts:
                yield AgentSessionEvent(kind="text", payload={"text": text})
            for chunk in thinking:
                yield AgentSessionEvent(kind="thinking", payload={"text": chunk})
            for record in tool_uses:
                yield AgentSessionEvent(
                    kind="tool_use",
                    payload={"name": record.name, "input": record.input, "id": record.tool_use_id},
                )
            continue
        if message_kind == "UserMessage":
            content = getattr(message, "content", None)
            if isinstance(content, list):
                for block in content:
                    if _block_kind(block) == "ToolResultBlock":
                        yield AgentSessionEvent(
                            kind="tool_result",
                            payload={
                                "tool_use_id": getattr(block, "tool_use_id", ""),
                                "is_error": getattr(block, "is_error", None),
                            },
                        )
            continue
        if message_kind == "ResultMessage":
            yield AgentSessionEvent(
                kind="result",
                payload={
                    "result": getattr(message, "result", None),
                    "is_error": getattr(message, "is_error", False),
                    "session_id": getattr(message, "session_id", None),
                    "duration_ms": getattr(message, "duration_ms", None),
                    "total_cost_usd": getattr(message, "total_cost_usd", None),
                    "num_turns": getattr(message, "num_turns", None),
                },
            )
            return
