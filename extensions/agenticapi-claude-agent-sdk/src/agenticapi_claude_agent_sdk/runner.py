"""High-level :class:`ClaudeAgentRunner` for AgenticAPI agent endpoints.

The runner is the recommended entry point for using the Claude Agent
SDK from inside an AgenticAPI app. It encapsulates options building,
the tool bridge, the permission adapter, message collection, and
optional audit recording, so a typical user-facing handler is just:

.. code-block:: python

    runner = ClaudeAgentRunner(system_prompt="You are a coding assistant")

    @app.agent_endpoint(name="assistant", autonomy_level="manual")
    async def assistant(intent, context):
        return await runner.run(intent=intent, context=context)

The runner is intentionally **stateless across calls**: each call to
:meth:`run` creates fresh permission state, builds fresh options, and
issues a fresh ``query()``. Multi-turn sessions are a future feature.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from agenticapi.harness.audit.trace import ExecutionTrace

from agenticapi_claude_agent_sdk._imports import load_sdk
from agenticapi_claude_agent_sdk.exceptions import ClaudeAgentSDKRunError
from agenticapi_claude_agent_sdk.messages import (
    AgentSessionEvent,
    AgentSessionResult,
    collect_session,
    stream_session_events,
)
from agenticapi_claude_agent_sdk.options import build_claude_agent_options
from agenticapi_claude_agent_sdk.permissions import HarnessPermissionAdapter
from agenticapi_claude_agent_sdk.tools import build_sdk_mcp_server_from_registry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from agenticapi.harness.audit.recorder import AuditRecorder
    from agenticapi.harness.policy.base import Policy
    from agenticapi.interface.intent import Intent
    from agenticapi.interface.response import AgentResponse
    from agenticapi.runtime.context import AgentContext
    from agenticapi.runtime.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


class ClaudeAgentRunner:
    """Run a Claude Agent SDK session inside an AgenticAPI endpoint.

    See module docstring for typical usage. Constructor arguments are
    bundled into the SDK ``ClaudeAgentOptions`` on every call to
    :meth:`run` so callers can mutate the runner's policies between
    requests if they need to.
    """

    def __init__(
        self,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        allowed_tools: Sequence[str] = (),
        disallowed_tools: Sequence[str] = (),
        permission_mode: str = "default",
        max_turns: int | None = None,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        tool_registry: ToolRegistry | None = None,
        policies: Sequence[Policy] = (),
        audit_recorder: AuditRecorder | None = None,
        extra_options: Mapping[str, Any] | None = None,
        mcp_server_name: str = "agenticapi",
        deny_unknown_tools: bool = False,
    ) -> None:
        """Initialize the runner.

        Args:
            system_prompt: System prompt sent to Claude. ``None`` uses
                the SDK default.
            model: Model identifier (e.g. ``"claude-sonnet-4-6"``).
                ``None`` uses the SDK default.
            allowed_tools: Built-in SDK tool names the model is allowed
                to use (e.g. ``["Read", "Glob", "Grep"]``). MCP tools
                from ``tool_registry`` are appended automatically.
            disallowed_tools: Tool names always denied. Takes precedence.
            permission_mode: SDK permission mode. One of ``"default"``,
                ``"acceptEdits"``, ``"plan"``, ``"bypassPermissions"``,
                ``"dontAsk"``, ``"auto"``.
            max_turns: Maximum agentic loop turns. ``None`` = SDK default.
            cwd: Working directory for the SDK CLI process.
            env: Extra environment variables for the SDK CLI process.
            tool_registry: Optional :class:`ToolRegistry` to expose to
                the model as MCP tools.
            policies: AgenticAPI policies to bridge into the SDK
                permission system.
            audit_recorder: Optional :class:`AuditRecorder`. When
                provided, every :meth:`run` records an
                :class:`ExecutionTrace` and the returned response's
                ``execution_trace_id`` is populated.
            extra_options: Free-form keyword arguments forwarded to
                :class:`ClaudeAgentOptions`. Useful for forward-compat
                with new SDK fields.
            mcp_server_name: Logical name for the MCP server bundling
                the AgenticAPI tools.
            deny_unknown_tools: When True, the permission adapter
                rejects any tool name not in ``allowed_tools`` or the
                MCP tool list. Recommended for production endpoints.
        """
        self._system_prompt = system_prompt
        self._model = model
        self._allowed_tools = list(allowed_tools)
        self._disallowed_tools = list(disallowed_tools)
        self._permission_mode = permission_mode
        self._max_turns = max_turns
        self._cwd = cwd
        self._env = dict(env) if env else None
        self._tool_registry = tool_registry
        self._policies = list(policies)
        self._audit_recorder = audit_recorder
        self._extra_options = dict(extra_options) if extra_options else None
        self._mcp_server_name = mcp_server_name
        self._deny_unknown_tools = deny_unknown_tools

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        *,
        intent: Intent[Any],
        context: AgentContext,
    ) -> AgentResponse:
        """Run a single agentic session for the given intent.

        Args:
            intent: The parsed AgenticAPI intent.
            context: The AgenticAPI execution context.

        Returns:
            An :class:`AgentResponse` summarising the session.

        Raises:
            ClaudeAgentSDKNotInstalledError: If ``claude_agent_sdk`` is
                not installed.
            ClaudeAgentSDKRunError: If the SDK reports the session ended
                in error.
        """
        sdk = load_sdk()
        adapter, options = self._build_options()

        prompt = self._build_prompt(intent, context)
        trace_id = uuid.uuid4().hex
        start = time.monotonic()

        logger.info(
            "claude_sdk_run_start",
            trace_id=trace_id,
            endpoint=context.endpoint_name,
            intent_action=intent.action.value,
            intent_domain=intent.domain,
        )

        try:
            session = await collect_session(
                sdk.query(prompt=prompt, options=options),
                raise_on_error=False,
            )
        except Exception as exc:
            logger.error("claude_sdk_run_failed", trace_id=trace_id, error=str(exc))
            raise

        duration_ms = (time.monotonic() - start) * 1000
        recorded_trace_id = await self._record_trace(
            trace_id=trace_id,
            session=session,
            intent=intent,
            context=context,
            duration_ms=duration_ms,
            permission_decisions=adapter.decisions,
        )

        if session.is_error:
            raise ClaudeAgentSDKRunError(
                f"Claude Agent SDK session ended with error (subtype={session.subtype})",
                subtype=session.subtype,
                session_id=session.session_id,
                errors=session.errors,
            )

        logger.info(
            "claude_sdk_run_complete",
            trace_id=trace_id,
            duration_ms=duration_ms,
            num_turns=session.num_turns,
            tool_calls=len(session.tool_calls),
            cost_usd=session.total_cost_usd,
        )

        return session.to_agent_response(execution_trace_id=recorded_trace_id)

    async def stream(
        self,
        *,
        intent: Intent[Any],
        context: AgentContext,
    ) -> AsyncIterator[AgentSessionEvent]:
        """Stream events from the SDK session as they happen.

        Yields :class:`AgentSessionEvent` objects suitable for
        forwarding to a Server-Sent-Events endpoint or a websocket.
        Audit recording is **not** performed for streamed sessions —
        callers can call :meth:`run` if they need traces.
        """
        sdk = load_sdk()
        _adapter, options = self._build_options()
        prompt = self._build_prompt(intent, context)

        async for event in stream_session_events(sdk.query(prompt=prompt, options=options)):
            yield event

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_options(self) -> tuple[HarnessPermissionAdapter, Any]:
        """Build the permission adapter and SDK options for one run."""
        mcp_servers: dict[str, Any] = {}
        mcp_tool_names: list[str] = []
        if self._tool_registry is not None and len(self._tool_registry) > 0:
            server, mcp_tool_names = build_sdk_mcp_server_from_registry(
                self._tool_registry,
                name=self._mcp_server_name,
            )
            mcp_servers[self._mcp_server_name] = server

        all_allowed = list(self._allowed_tools) + mcp_tool_names
        adapter = HarnessPermissionAdapter(
            policies=self._policies,
            allowed_tool_names=all_allowed,
            denied_tool_names=self._disallowed_tools,
            deny_unknown_tools=self._deny_unknown_tools,
        )

        options = build_claude_agent_options(
            system_prompt=self._system_prompt,
            model=self._model,
            allowed_tools=all_allowed,
            disallowed_tools=self._disallowed_tools,
            permission_mode=self._permission_mode,
            max_turns=self._max_turns,
            cwd=self._cwd,
            env=self._env,
            mcp_servers=mcp_servers or None,
            permission_adapter=adapter,
            extra_options=self._extra_options,
        )
        return adapter, options

    def _build_prompt(self, intent: Intent[Any], context: AgentContext) -> str:
        """Build the prompt string sent to ``query()``.

        We start from the raw intent and append a small context block
        when the AgenticAPI ``ContextWindow`` has anything to add.
        """
        prompt = intent.raw
        context_str = context.context_window.build()
        if context_str:
            prompt = f"{prompt}\n\n<context>\n{context_str}\n</context>"
        return prompt

    async def _record_trace(
        self,
        *,
        trace_id: str,
        session: AgentSessionResult,
        intent: Intent[Any],
        context: AgentContext,
        duration_ms: float,
        permission_decisions: list[Any],
    ) -> str | None:
        """Record an ExecutionTrace if an audit recorder is configured."""
        if self._audit_recorder is None:
            return None

        recorder: AuditRecorder = self._audit_recorder
        trace = ExecutionTrace(
            trace_id=trace_id,
            endpoint_name=context.endpoint_name,
            timestamp=datetime.now(tz=UTC),
            intent_raw=intent.raw,
            intent_action=intent.action.value,
            generated_code=_collected_code(session) or "",
            reasoning=session.thinking or None,
            execution_duration_ms=duration_ms,
            execution_result=session.result_text or session.text or None,
            error=("; ".join(session.errors) if session.errors else None),
        )
        trace.policy_evaluations = [
            {
                "tool": d.tool_name,
                "allowed": d.allowed,
                "reason": d.reason,
                "violations": d.violations,
            }
            for d in permission_decisions
        ]
        await recorder.record(trace)
        return trace_id


def _collected_code(session: AgentSessionResult) -> str | None:
    """Build a single Markdown-ish view of every code-bearing tool call."""
    snippets: list[str] = []
    for call in session.tool_calls:
        for source_field in ("command", "content", "new_string"):
            if source_field in call.input:
                snippets.append(f"# tool={call.name} field={source_field}\n{call.input[source_field]}")
                break
    if not snippets:
        return None
    return "\n\n".join(snippets)
