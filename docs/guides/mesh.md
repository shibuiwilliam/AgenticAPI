# Agent Mesh

The `AgentMesh` enables multi-agent orchestration within a single `AgenticApp`. It provides decorator-based registration for **roles** (individual agent handlers) and **orchestrators** (handlers that compose roles into pipelines).

## Why use a mesh?

When a task requires multiple specialized agents working together -- a researcher that gathers data, an analyst that processes it, a writer that formats the output -- you need a way to compose them with:

- **Cycle detection** -- prevent infinite loops when roles call each other
- **Budget propagation** -- enforce a total cost ceiling across all sub-calls
- **Trace linkage** -- link sub-agent audit traces to the parent request

`AgentMesh` provides all three out of the box.

## Quick start

```python
from agenticapi import AgenticApp
from agenticapi.mesh import AgentMesh

app = AgenticApp(title="Research Pipeline")
mesh = AgentMesh(app=app, name="research")

@mesh.role(name="researcher")
async def researcher(payload, ctx):
    """Gather research on the given topic."""
    return {"topic": str(payload), "points": ["point A", "point B"]}

@mesh.role(name="summarizer")
async def summarizer(payload, ctx):
    """Summarize research results."""
    return {"summary": f"Key findings: {payload}"}

@mesh.orchestrator(name="pipeline", roles=["researcher", "summarizer"])
async def pipeline(intent, mesh_ctx):
    """Run the full research pipeline."""
    research = await mesh_ctx.call("researcher", intent.raw)
    summary = await mesh_ctx.call("summarizer", research)
    return summary
```

This registers three endpoints: `/agent/researcher`, `/agent/summarizer`, and `/agent/pipeline`. The orchestrator calls roles via `MeshContext.call()`.

## MeshContext

The `MeshContext` is injected into orchestrator handlers and provides:

### `call(role, payload)`

Invoke a named role within the mesh. Before each call, the context:

1. **Checks for cycles** -- if the role already appears in the call stack, raises `MeshCycleError`
2. **Checks budget** -- if `budget_usd` was set on the orchestrator and the budget is exhausted, raises `BudgetExceeded`
3. **Builds a child trace** -- the child trace ID is `{parent}:{role}:{uuid8}` for audit linkage

### Budget enforcement

```python
@mesh.orchestrator(name="pipeline", roles=["researcher"], budget_usd=1.00)
async def pipeline(intent, mesh_ctx):
    # Total spend across all sub-calls is capped at $1.00
    result = await mesh_ctx.call("researcher", intent.raw)
    return result
```

## How it works

- `@mesh.role` registers the handler in the mesh's internal role registry **and** calls `app.agent_endpoint()` to create a normal HTTP endpoint
- `@mesh.orchestrator` does the same for orchestrators, wrapping the handler to inject `MeshContext`
- Roles and orchestrators appear in `/docs`, `/capabilities`, and the OpenAPI schema like any other endpoint
- All execution is in-process (same event loop) -- cross-process mesh is a future goal (see `VISION.md` Track 1)

## Limitations

- **In-process only** -- roles must be registered on the same `AgenticApp`
- **No automatic LLM cost tracking** -- `budget_usd` is checked by `MeshContext` but not yet integrated with `BudgetPolicy` per-request scopes
- **Sequential calls** -- `MeshContext.call()` is sequential; parallel role invocation is not yet supported

## Reference

- Source: `src/agenticapi/mesh/mesh.py`, `src/agenticapi/mesh/context.py`
- Example: `examples/24_multi_agent_pipeline/`
- Public API: `AgentMesh`, `MeshContext`, `MeshCycleError`
