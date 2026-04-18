"""Agent Workflow example: document analysis pipeline.

Demonstrates AgenticAPI's **declarative workflow engine** — multi-step
agent processes with typed state, conditional branching, and
checkpoint pauses for human review.

Features demonstrated:

- **``WorkflowState`` subclass** — typed state that accumulates
  across steps.
- **Conditional branching** — risk assessment routes to human
  review only for high-risk documents.
- **Checkpoint pause/resume** — workflow pauses at the review step
  and can be resumed with new input.
- **``WorkflowContext.call_tool``** — governed tool calls within
  workflow steps.
- **``to_mermaid()``** — workflow graph export for documentation.

Run with::

    uvicorn examples.30_agent_workflow.app:app --reload

Test with curl::

    # Run the analysis pipeline (low-risk document)
    curl -X POST http://127.0.0.1:8000/agent/analyze \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Analyze this quarterly report"}'

    # Inspect the workflow graph
    curl -X POST http://127.0.0.1:8000/agent/workflow_graph \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "show graph"}'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import Field

from agenticapi import AgenticApp, tool
from agenticapi.runtime.tools.registry import ToolRegistry
from agenticapi.workflow import AgentWorkflow, WorkflowContext, WorkflowState

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# Workflow state
# ---------------------------------------------------------------------------


class AnalysisState(WorkflowState):
    """State that flows through the analysis pipeline."""

    document_text: str = ""
    summary: str = ""
    key_findings: list[str] = Field(default_factory=list)
    risk_level: str = "unknown"
    report: str = ""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(description="Extract text from a document")
async def extract_text(document_id: str) -> str:
    """Simulate document text extraction."""
    return (
        "Q1 revenue grew 15% YoY to $2.3B. Operating margins "
        "improved to 28%. No material risks identified. Customer "
        "retention rate at 94%."
    )


@tool(description="Classify risk level of document content")
async def classify_risk(text: str) -> dict[str, Any]:
    """Simulate risk classification."""
    if "material risks" in text.lower() and "no" not in text.lower():
        return {"risk_level": "high", "reason": "Material risks identified"}
    return {"risk_level": "low", "reason": "No material risks found"}


registry = ToolRegistry()
registry.register(extract_text)
registry.register(classify_risk)


# ---------------------------------------------------------------------------
# Workflow definition
# ---------------------------------------------------------------------------

workflow: AgentWorkflow[AnalysisState] = AgentWorkflow(
    name="document_analysis",
    state_class=AnalysisState,
)


@workflow.step("parse")
async def parse(state: AnalysisState, ctx: WorkflowContext) -> str:
    """Extract text from the document."""
    state.document_text = await ctx.call_tool("extract_text", document_id="doc-001")
    return "analyze"


@workflow.step("analyze")
async def analyze(state: AnalysisState, ctx: WorkflowContext) -> str:
    """Generate summary and findings from the text."""
    state.summary = "Q1 performance strong with 15% revenue growth and improved margins."
    state.key_findings = [
        "Revenue grew 15% YoY to $2.3B",
        "Operating margins improved to 28%",
        "Customer retention at 94%",
    ]
    return "assess_risk"


@workflow.step("assess_risk")
async def assess_risk(state: AnalysisState, ctx: WorkflowContext) -> str:
    """Classify risk level and route accordingly."""
    result = await ctx.call_tool("classify_risk", text=state.document_text)
    state.risk_level = result["risk_level"]
    if state.risk_level == "high":
        return "review"
    return "report"


@workflow.step("review", checkpoint=True)
async def review(state: AnalysisState, ctx: WorkflowContext) -> str:
    """Pause for human review (high-risk documents only)."""
    return "report"


@workflow.step("report")
async def report(state: AnalysisState, ctx: WorkflowContext) -> None:
    """Generate the final report."""
    state.report = (
        f"# Document Analysis Report\n\n"
        f"## Summary\n{state.summary}\n\n"
        f"## Key Findings\n"
        + "\n".join(f"- {f}" for f in state.key_findings)
        + f"\n\n## Risk Level: {state.risk_level.upper()}\n"
    )
    return None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Document Analysis (Workflow Engine)",
    description="Multi-step document analysis with conditional branching and checkpoints.",
    tools=registry,
)


@app.agent_endpoint(
    name="analyze",
    description="Analyze a document through the pipeline",
    workflow=workflow,
)
async def analyze_endpoint(intent: Any, context: AgentContext) -> dict[str, Any]:
    """Fallback handler (only runs when workflow is not set)."""
    return {"message": "Workflow not configured."}


@app.agent_endpoint(name="workflow_graph", description="Show the workflow graph")
async def graph_endpoint(intent: Any, context: AgentContext) -> dict[str, str]:
    """Return the Mermaid graph of the workflow."""
    return {"mermaid": workflow.to_mermaid()}
