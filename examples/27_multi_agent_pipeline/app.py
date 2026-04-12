"""Multi-agent pipeline with AgentMesh.

Demonstrates a 3-role research pipeline: researcher → summariser → reviewer.
All roles run in-process with budget propagation and trace linkage.

Prerequisites:
    pip install agenticapi

Run:
    agenticapi dev --app examples.27_multi_agent_pipeline.app:app

Test:
    curl -X POST http://localhost:8000/agent/research_pipeline \\
      -H "Content-Type: application/json" \\
      -d '{"intent": "quantum computing"}'

    # Hit individual roles directly:
    curl -X POST http://localhost:8000/agent/researcher \\
      -H "Content-Type: application/json" \\
      -d '{"intent": "machine learning"}'
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agenticapi import AgenticApp, AgentMesh

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.mesh.context import MeshContext

# ── App + Mesh ───────────────────────────────────────────────────────
app = AgenticApp(title="Research Pipeline")
mesh = AgentMesh(app=app, name="research")


# ── Roles ────────────────────────────────────────────────────────────
@mesh.role(name="researcher", description="Research a topic and return key points")
async def researcher(payload: str, ctx: MeshContext) -> dict:
    """Simulate a research agent."""
    return {
        "topic": payload,
        "points": [
            f"Key finding 1 about {payload}",
            f"Key finding 2 about {payload}",
            f"Key finding 3 about {payload}",
        ],
        "sources": ["arxiv", "scholar"],
    }


@mesh.role(name="summariser", description="Summarise research findings")
async def summariser(payload: str, ctx: MeshContext) -> dict:
    """Simulate a summariser agent."""
    return {
        "summary": f"Summary of research: {payload[:100]}...",
        "word_count": 42,
    }


@mesh.role(name="reviewer", description="Review and approve summaries")
async def reviewer(payload: str, ctx: MeshContext) -> dict:
    """Simulate a review agent."""
    return {
        "approved": True,
        "confidence": 0.92,
        "feedback": "Well-structured findings with credible sources.",
    }


# ── Orchestrator ─────────────────────────────────────────────────────
@mesh.orchestrator(
    name="research_pipeline",
    roles=["researcher", "summariser", "reviewer"],
    description="End-to-end research pipeline: research → summarise → review",
    budget_usd=1.00,
)
async def research_pipeline(intent: Intent, mesh_ctx: MeshContext) -> dict:
    """Orchestrate a 3-stage research pipeline."""
    research = await mesh_ctx.call("researcher", intent.raw)
    summary = await mesh_ctx.call("summariser", str(research))
    review = await mesh_ctx.call("reviewer", str(summary))

    return {
        "topic": intent.raw,
        "research": research,
        "summary": summary,
        "review": review,
    }
