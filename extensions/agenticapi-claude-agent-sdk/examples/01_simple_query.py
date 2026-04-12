"""Minimal Claude Agent SDK runner inside an AgenticAPI endpoint.

Prerequisites:
    pip install agentharnessapi agentharnessapi-claude-agent-sdk
    export ANTHROPIC_API_KEY=sk-...

Run:
    uvicorn examples.01_simple_query:app --reload

Test:
    curl -X POST http://localhost:8000/agent/assistant \
        -H 'content-type: application/json' \
        -d '{"intent": "Summarise what AgenticAPI does in one sentence."}'
"""

from __future__ import annotations

from agenticapi import AgenticApp
from agenticapi.ext.claude_agent_sdk import ClaudeAgentRunner

app = AgenticApp(title="claude-agent-sdk demo — simple query")

runner = ClaudeAgentRunner(
    system_prompt="You are a concise, helpful assistant.",
    permission_mode="bypassPermissions",  # no tools enabled
)


@app.agent_endpoint(name="assistant", autonomy_level="manual")
async def assistant(intent, context):  # type: ignore[no-untyped-def]
    """Forward every request straight to the SDK runner."""
    return await runner.run(intent=intent, context=context)
