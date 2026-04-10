"""Run the SDK with full audit trace recording.

This example wires the runner up to an :class:`AuditRecorder` so
every session is captured as an :class:`ExecutionTrace`. The trace
is exposed at ``GET /audit/{trace_id}`` for inspection.

Prerequisites:
    pip install agenticapi agenticapi-claude-agent-sdk
    export ANTHROPIC_API_KEY=sk-...

Run:
    uvicorn examples.03_with_audit:app --reload
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agenticapi import AgenticApp
from agenticapi.harness.audit.recorder import AuditRecorder
from starlette.responses import JSONResponse
from starlette.routing import Route

from agenticapi_claude_agent_sdk import ClaudeAgentRunner

if TYPE_CHECKING:
    from starlette.requests import Request

audit_recorder = AuditRecorder()

runner = ClaudeAgentRunner(
    system_prompt="You are an audited assistant. Be brief.",
    audit_recorder=audit_recorder,
    permission_mode="bypassPermissions",
)

app = AgenticApp(title="claude-agent-sdk demo — audit")


@app.agent_endpoint(name="assistant", autonomy_level="manual")
async def assistant(intent, context):  # type: ignore[no-untyped-def]
    return await runner.run(intent=intent, context=context)


async def get_audit(request: Request) -> JSONResponse:
    trace_id = request.path_params["trace_id"]
    for record in audit_recorder.get_records():
        if record.trace_id == trace_id:
            return JSONResponse(
                {
                    "trace_id": record.trace_id,
                    "endpoint": record.endpoint_name,
                    "intent": record.intent_raw,
                    "duration_ms": record.execution_duration_ms,
                    "policy_evaluations": record.policy_evaluations,
                    "result": record.execution_result,
                    "error": record.error,
                }
            )
    return JSONResponse({"error": "trace not found"}, status_code=404)


app.add_routes([Route("/audit/{trace_id}", get_audit, methods=["GET"])])
