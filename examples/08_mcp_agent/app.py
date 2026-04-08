"""MCP Server example: expose agent endpoints as MCP tools.

Demonstrates:
- ``enable_mcp=True`` on select endpoints to expose them as MCP tools
- ``expose_as_mcp()`` convenience function to mount the MCP server
- Selective MCP exposure (only query/analytics, not admin)
- MCP tools accessible via streamable-http transport at ``/mcp``
- All endpoints remain accessible via the native intent API

Prerequisites:
    pip install agenticapi[mcp]

Run with:
    uvicorn examples.08_mcp_agent.app:app --reload

Test native API:
    curl -X POST http://127.0.0.1:8000/agent/tasks.query \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show all high-priority tasks"}'

    curl -X POST http://127.0.0.1:8000/agent/tasks.analytics \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "What is the completion rate?"}'

    curl -X POST http://127.0.0.1:8000/agent/tasks.admin \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Reset all task statuses"}'

    curl http://127.0.0.1:8000/health

Test MCP with the MCP Inspector:
    npx @modelcontextprotocol/inspector http://127.0.0.1:8000/mcp

The MCP inspector will show two tools (tasks.query and tasks.analytics)
but NOT tasks.admin, which has enable_mcp=False (the default).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi.app import AgenticApp
from agenticapi.interface.compat.mcp import expose_as_mcp
from agenticapi.interface.response import AgentResponse
from agenticapi.routing import AgentRouter

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# --- Mock data ---

TASKS = [
    {"id": 1, "title": "Fix login bug", "priority": "high", "status": "open", "assignee": "alice"},
    {"id": 2, "title": "Add dark mode", "priority": "medium", "status": "in_progress", "assignee": "bob"},
    {"id": 3, "title": "Write API docs", "priority": "low", "status": "completed", "assignee": "charlie"},
    {"id": 4, "title": "Upgrade database", "priority": "high", "status": "open", "assignee": "alice"},
    {"id": 5, "title": "Refactor auth module", "priority": "medium", "status": "completed", "assignee": "bob"},
]

# --- Router ---

router = AgentRouter(prefix="tasks", tags=["tasks"])


@router.agent_endpoint(
    name="query",
    description="Query and search tasks by status, priority, or assignee",
    enable_mcp=True,
    autonomy_level="auto",
)
async def task_query(intent: Intent, context: AgentContext) -> AgentResponse:
    """Query tasks. Exposed as an MCP tool."""
    priority_filter = intent.parameters.get("priority")
    status_filter = intent.parameters.get("status")

    results = TASKS
    if priority_filter:
        results = [t for t in results if t["priority"] == priority_filter]
    if status_filter:
        results = [t for t in results if t["status"] == status_filter]

    return AgentResponse(
        result={"tasks": results, "count": len(results)},
        reasoning=f"Found {len(results)} tasks matching the query",
    )


@router.agent_endpoint(
    name="analytics",
    description="Task analytics: completion rate, priority breakdown, assignee workload",
    enable_mcp=True,
    autonomy_level="auto",
)
async def task_analytics(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Compute task analytics. Exposed as an MCP tool."""
    total = len(TASKS)
    completed = sum(1 for t in TASKS if t["status"] == "completed")
    by_priority: dict[str, int] = {}
    by_assignee: dict[str, int] = {}

    for task in TASKS:
        by_priority[task["priority"]] = by_priority.get(task["priority"], 0) + 1
        by_assignee[task["assignee"]] = by_assignee.get(task["assignee"], 0) + 1

    return {
        "total_tasks": total,
        "completion_rate": completed / total if total else 0,
        "by_priority": by_priority,
        "by_assignee": by_assignee,
    }


@router.agent_endpoint(
    name="admin",
    description="Administrative operations on tasks (not exposed via MCP)",
    autonomy_level="supervised",
)
async def task_admin(intent: Intent, context: AgentContext) -> dict[str, str]:
    """Admin operations. NOT exposed as MCP tool (enable_mcp defaults to False)."""
    return {"message": f"Admin operation requested: {intent.raw}", "status": "pending_review"}


# --- App assembly ---

app = AgenticApp(title="MCP Task Tracker", version="0.1.0")
app.include_router(router)

# Mount MCP server — only tasks.query and tasks.analytics become MCP tools
expose_as_mcp(app, path="/mcp")
