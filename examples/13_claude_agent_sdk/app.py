"""Claude Agent SDK extension example: full agentic loop inside an endpoint.

Demonstrates the ``agenticapi-claude-agent-sdk`` extension, which lets you
run a full Claude Agent SDK session (planning + tool use + reflection)
inside an AgenticAPI endpoint, while preserving AgenticAPI's harness
guarantees: declarative policies, an audit trail, and a tool registry.

What this example shows:

* ``ClaudeAgentRunner`` wired up with a ``CodePolicy``, an ``AuditRecorder``,
  and an in-process ``ToolRegistry`` so the model can call AgenticAPI tools
  via MCP under the same allow-list rules as native SDK tools.
* An ``assistant.ask`` endpoint that delegates to the runner.
* A read-only ``assistant.audit`` endpoint that returns the last few
  recorded execution traces — useful for showing what the runner actually
  did on the previous request.
* Graceful degradation: if the extension or the SDK is not installed, the
  example still imports cleanly and the endpoint returns a structured
  error response explaining how to install it.

Prerequisites:
    pip install agenticapi-claude-agent-sdk
    export ANTHROPIC_API_KEY=sk-ant-...

Run with:
    uvicorn examples.13_claude_agent_sdk.app:app --reload

Test with curl:
    # Ask the agent something
    curl -X POST http://127.0.0.1:8000/agent/assistant.ask \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Summarise what AgenticAPI does in one sentence."}'

    # Inspect what the runner did on the last call
    curl -X POST http://127.0.0.1:8000/agent/assistant.audit \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show recent traces"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from agenticapi import AgenticApp, CodePolicy
from agenticapi.harness.audit.recorder import AuditRecorder
from agenticapi.routing import AgentRouter
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition
from agenticapi.runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# Tools the agent is allowed to call
# ---------------------------------------------------------------------------


class FaqTool:
    """A tiny in-memory FAQ source the model can query.

    Demonstrates how an arbitrary AgenticAPI ``Tool`` becomes callable from
    the Claude Agent SDK loop without the user writing any MCP plumbing —
    the runner registers it as ``mcp__agenticapi__faq`` automatically.
    """

    _ENTRIES: ClassVar[dict[str, str]] = {
        "agenticapi": (
            "AgenticAPI is an agent-native Python web framework with a "
            "policy/sandbox/audit harness for safe LLM code execution."
        ),
        "harness": (
            "The harness is the safety pipeline that evaluates, sandboxes, "
            "and audits every piece of LLM-generated code before execution."
        ),
        "claude-agent-sdk": (
            "The Claude Agent SDK runs full agentic loops (planning, tool "
            "use, reflection). The agenticapi-claude-agent-sdk extension "
            "wraps it for use inside AgenticAPI endpoints."
        ),
    }

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="faq",
            description="Look up an answer in the AgenticAPI FAQ by topic keyword.",
            capabilities=[ToolCapability.READ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic keyword to look up (e.g. 'harness').",
                    }
                },
                "required": ["topic"],
            },
        )

    async def invoke(self, **kwargs: Any) -> Any:
        topic = str(kwargs.get("topic", "")).lower().strip()
        if not topic:
            return {"error": "topic is required"}
        for key, answer in self._ENTRIES.items():
            if key in topic or topic in key:
                return {"topic": key, "answer": answer}
        return {"topic": topic, "answer": None, "known_topics": list(self._ENTRIES)}


# ---------------------------------------------------------------------------
# Runner setup (lazy: only built if the extension is importable)
# ---------------------------------------------------------------------------


def _build_runner() -> tuple[Any, AuditRecorder] | None:
    """Build a ``ClaudeAgentRunner`` if the extension is installed.

    Returns ``None`` when ``agenticapi_claude_agent_sdk`` is missing, so
    that the rest of the app still imports cleanly. Note: the SDK itself
    can be missing too — the runner only loads it on the first ``run()``
    call.
    """
    try:
        from agenticapi_claude_agent_sdk import ClaudeAgentRunner
    except ImportError:
        return None

    registry = ToolRegistry()
    registry.register(FaqTool())

    recorder = AuditRecorder()
    runner = ClaudeAgentRunner(
        system_prompt=(
            "You are a concise assistant for the AgenticAPI project. "
            "When the user asks about AgenticAPI concepts, call the `faq` "
            "tool to look them up. Reply in one or two sentences."
        ),
        # Read-only built-in tools — the SDK Loop can also peek at files.
        allowed_tools=["Read", "Glob", "Grep"],
        # AgenticAPI policies are bridged into the SDK permission system.
        policies=[
            CodePolicy(
                denied_modules=["os", "subprocess", "sys", "socket"],
                deny_eval_exec=True,
                deny_dynamic_import=True,
            ),
        ],
        permission_mode="default",
        deny_unknown_tools=True,
        max_turns=4,
        tool_registry=registry,
        audit_recorder=recorder,
    )
    return runner, recorder


_runner_pair = _build_runner()
runner = _runner_pair[0] if _runner_pair else None
audit_recorder = _runner_pair[1] if _runner_pair else AuditRecorder()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


router = AgentRouter(prefix="assistant", tags=["assistant"])


@router.agent_endpoint(
    name="ask",
    description="Run a full Claude Agent SDK session for the given intent.",
    autonomy_level="manual",
)
async def ask(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Delegate the user's intent to the Claude Agent SDK runner.

    ``autonomy_level="manual"`` keeps AgenticAPI's own harness pipeline out
    of the way; the runner is the single source of safety enforcement for
    this endpoint, with policies bridged into the SDK's permission system.

    Returns a plain dict (the framework wraps it in an :class:`AgentResponse`
    automatically) containing the runner's answer plus the metadata users
    most often want to inspect: reasoning, generated code, trace id, and
    any error.
    """
    if runner is None:
        return {
            "answer": None,
            "ok": False,
            "error": "extension_not_installed",
            "message": (
                "agenticapi-claude-agent-sdk is not installed. Install it with: pip install agenticapi-claude-agent-sdk"
            ),
            "intent": intent.raw,
        }

    try:
        runner_response = await runner.run(intent=intent, context=context)
    except Exception as exc:  # surface SDK errors as a structured payload
        # Common case: ANTHROPIC_API_KEY not set, or the Claude CLI is not
        # available. We return a structured error so the example is still
        # useful for inspection without an API key.
        return {
            "answer": None,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "intent": intent.raw,
        }

    return {
        "answer": runner_response.result,
        "ok": runner_response.status == "completed",
        "reasoning": runner_response.reasoning,
        "generated_code": runner_response.generated_code,
        "execution_trace_id": runner_response.execution_trace_id,
        "error": runner_response.error,
    }


@router.agent_endpoint(
    name="audit",
    description="Return the most recent audit traces recorded by the runner.",
    autonomy_level="auto",
)
async def audit(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Show the audit trail produced by the runner.

    Doesn't talk to the SDK at all — it just reads from the in-memory
    ``AuditRecorder`` populated by the ``ask`` endpoint, so it's safe to
    use even when the SDK isn't installed.
    """
    del intent, context
    records = audit_recorder.get_records()
    summary = [
        {
            "trace_id": r.trace_id,
            "endpoint": r.endpoint_name,
            "intent": r.intent_raw,
            "duration_ms": round(r.execution_duration_ms, 2),
            "policy_decisions": len(r.policy_evaluations),
            "error": r.error,
        }
        for r in records[-10:]  # last 10 only
    ]
    return {
        "extension_installed": runner is not None,
        "trace_count": len(records),
        "recent": summary,
    }


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Claude Agent SDK Example",
    version="0.1.0",
    description=(
        "Demonstrates the agenticapi-claude-agent-sdk extension running a "
        "full Claude agentic loop inside an AgenticAPI endpoint, with "
        "policies bridged into the SDK permission system and an audit trail."
    ),
)
app.include_router(router)
