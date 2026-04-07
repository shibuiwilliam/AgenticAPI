"""Minimal AgenticAPI example -- Hello Agent.

Run with:
    uvicorn examples.01_hello_agent.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.01_hello_agent.app:app

Test with curl:
    curl -X POST http://127.0.0.1:8000/agent/greeter \
        -H "Content-Type: application/json" \
        -d '{"intent": "Hello, how are you?"}'
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agenticapi import AgenticApp, AgentResponse, Intent

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="Hello Agent")


@app.agent_endpoint(
    name="greeter",
    description="A simple greeting agent",
    autonomy_level="auto",
)
async def greeter(intent: Intent, context: AgentContext) -> AgentResponse:
    """Simple agent that greets users."""
    return AgentResponse(
        result={"message": f"Hello! You said: {intent.raw}"},
        generated_code=None,
        reasoning="Direct greeting response",
    )
