"""OpenAI-powered agent example with code generation and custom prompts.

Demonstrates:
- OpenAIBackend for LLM-powered code generation
- Custom prompts: calling the LLM directly with endpoint-specific system prompts
- HarnessEngine with CodePolicy and DataPolicy
- DatabaseTool and CacheTool for agent-generated code
- ApprovalWorkflow for write operations

Prerequisites:
    export OPENAI_API_KEY="sk-..."

Run with:
    uvicorn examples.03_openai_agent.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.03_openai_agent.app:app

Test with curl:
    # Read query (handler-based)
    curl -X POST http://127.0.0.1:8000/agent/tasks.query \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show me all high-priority tasks"}'

    # LLM-powered summarize (custom prompt)
    curl -X POST http://127.0.0.1:8000/agent/tasks.summarize \
        -H "Content-Type: application/json" \
        -d '{"intent": "Give me a brief status update on the project"}'

    # LLM-powered prioritize (custom prompt)
    curl -X POST http://127.0.0.1:8000/agent/tasks.prioritize \
        -H "Content-Type: application/json" \
        -d '{"intent": "What should Alice work on next?"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

import json as _json
import os
from typing import TYPE_CHECKING, Any

from agenticapi.app import AgenticApp
from agenticapi.harness.approval.rules import ApprovalRule
from agenticapi.harness.approval.workflow import ApprovalWorkflow
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.interface.intent import Intent, IntentScope
from agenticapi.interface.response import AgentResponse
from agenticapi.routing import AgentRouter
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.llm.openai import OpenAIBackend
from agenticapi.runtime.tools.cache import CacheTool
from agenticapi.runtime.tools.database import DatabaseTool
from agenticapi.runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# Mock data — a simple task tracker
# ---------------------------------------------------------------------------

TASKS = [
    {"id": 1, "title": "Design API schema", "assignee": "Alice", "priority": "high", "status": "done"},
    {"id": 2, "title": "Implement auth", "assignee": "Bob", "priority": "high", "status": "in_progress"},
    {"id": 3, "title": "Write unit tests", "assignee": "Alice", "priority": "medium", "status": "done"},
    {"id": 4, "title": "Set up CI/CD", "assignee": "Charlie", "priority": "medium", "status": "todo"},
    {"id": 5, "title": "Load testing", "assignee": "Bob", "priority": "low", "status": "todo"},
    {"id": 6, "title": "Security audit", "assignee": "Diana", "priority": "high", "status": "in_progress"},
    {"id": 7, "title": "Documentation", "assignee": "Charlie", "priority": "low", "status": "done"},
    {"id": 8, "title": "Deploy to staging", "assignee": "Alice", "priority": "high", "status": "todo"},
]


async def mock_db_execute(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Simulate database queries against the task list."""
    q = query.lower()
    if "task" in q:
        return TASKS
    return []


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

db_tool = DatabaseTool(
    name="task_db",
    description="Task tracker database with a 'tasks' table. Columns: id, title, assignee, priority, status.",
    execute_fn=mock_db_execute,
    read_only=True,
)

cache_tool = CacheTool(
    name="task_cache",
    description="Cache for task query results",
    default_ttl_seconds=120,
)

tools = ToolRegistry()
tools.register(db_tool)
tools.register(cache_tool)

# ---------------------------------------------------------------------------
# Policies — control what generated code can do
# ---------------------------------------------------------------------------

code_policy = CodePolicy(
    denied_modules=["os", "subprocess", "shutil", "sys", "importlib", "pathlib"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
    allow_network=False,
    max_code_lines=200,
)

data_policy = DataPolicy(
    readable_tables=["tasks"],
    writable_tables=["tasks"],
    restricted_columns=["password_hash", "api_key"],
    deny_ddl=True,
    max_result_rows=500,
)

# ---------------------------------------------------------------------------
# Approval — write operations require a project lead
# ---------------------------------------------------------------------------

approval_workflow = ApprovalWorkflow(
    rules=[
        ApprovalRule(
            name="task_write_approval",
            require_for_actions=["write", "execute"],
            require_for_domains=["task"],
            approvers=["project_lead"],
            timeout_seconds=1800,
        ),
    ],
)

# ---------------------------------------------------------------------------
# Harness — the safety layer wrapping all code execution
# ---------------------------------------------------------------------------

harness = HarnessEngine(
    policies=[code_policy, data_policy],
    approval_workflow=approval_workflow,
)

# ---------------------------------------------------------------------------
# LLM backend — OpenAI GPT
# ---------------------------------------------------------------------------
# The backend requires OPENAI_API_KEY to be set. When absent the app still
# starts but falls back to direct handler invocation (no code generation).

llm = OpenAIBackend(model="gpt-4o-mini") if os.environ.get("OPENAI_API_KEY") else None

# ---------------------------------------------------------------------------
# Routers and endpoints
# ---------------------------------------------------------------------------

tasks_router = AgentRouter(prefix="tasks", tags=["tasks"])


@tasks_router.agent_endpoint(
    name="query",
    description="Query tasks: list, search, filter by assignee/priority/status",
    intent_scope=IntentScope(allowed_intents=["task.*", "*.read", "*.analyze", "*.clarify"]),
    autonomy_level="auto",
)
async def task_query(intent: Intent, context: AgentContext) -> AgentResponse:
    """Handle task read queries directly (no LLM needed for simple lookups)."""
    priority_filter = intent.parameters.get("priority")
    assignee_filter = intent.parameters.get("assignee")
    status_filter = intent.parameters.get("status")

    results = TASKS
    if priority_filter:
        results = [t for t in results if t["priority"] == priority_filter]
    if assignee_filter:
        results = [t for t in results if t["assignee"].lower() == assignee_filter.lower()]
    if status_filter:
        results = [t for t in results if t["status"] == status_filter]

    return AgentResponse(
        result={"tasks": results, "count": len(results)},
        reasoning=f"Filtered {len(TASKS)} tasks to {len(results)} results",
    )


@tasks_router.agent_endpoint(
    name="analytics",
    description="Task analytics: completion rates, workload distribution, priority breakdown",
    intent_scope=IntentScope(allowed_intents=["task.*", "*.read", "*.analyze", "*.clarify"]),
    autonomy_level="auto",
)
async def task_analytics(intent: Intent, context: AgentContext) -> AgentResponse:
    """Compute analytics over the task list."""
    total = len(TASKS)
    done = sum(1 for t in TASKS if t["status"] == "done")
    in_progress = sum(1 for t in TASKS if t["status"] == "in_progress")
    todo = sum(1 for t in TASKS if t["status"] == "todo")

    by_assignee: dict[str, dict[str, int]] = {}
    for task in TASKS:
        name = task["assignee"]
        by_assignee.setdefault(name, {"total": 0, "done": 0})
        by_assignee[name]["total"] += 1
        if task["status"] == "done":
            by_assignee[name]["done"] += 1

    by_priority: dict[str, int] = {}
    for task in TASKS:
        p = task["priority"]
        by_priority[p] = by_priority.get(p, 0) + 1

    return AgentResponse(
        result={
            "summary": {
                "total": total,
                "done": done,
                "in_progress": in_progress,
                "todo": todo,
                "completion_rate": round(done / total, 2) if total else 0,
            },
            "by_assignee": {
                name: {**stats, "completion_rate": round(stats["done"] / stats["total"], 2)}
                for name, stats in by_assignee.items()
            },
            "by_priority": by_priority,
        },
        reasoning="Aggregated task statistics across all assignees and priorities",
    )


@tasks_router.agent_endpoint(
    name="update",
    description="Update task status, reassign tasks, change priorities",
    intent_scope=IntentScope(
        allowed_intents=["task.write", "task.execute"],
        denied_intents=["task.bulk_delete"],
    ),
    autonomy_level="supervised",
)
async def task_update(intent: Intent, context: AgentContext) -> AgentResponse:
    """Handle task updates (requires approval via the harness)."""
    return AgentResponse(
        result={"message": f"Update requested: {intent.raw}"},
        status="pending_review",
        reasoning="Write operations on tasks require project lead approval",
    )


# ---------------------------------------------------------------------------
# Custom prompt endpoints — call the LLM directly with specific prompts
# ---------------------------------------------------------------------------


@tasks_router.agent_endpoint(
    name="summarize",
    description="LLM-powered project summary using a custom prompt",
    intent_scope=IntentScope(allowed_intents=["*"]),
    autonomy_level="manual",  # bypass harness — handler calls LLM directly
)
async def task_summarize(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Call OpenAI with a custom summarization prompt and task data."""
    if llm is None:
        return {"error": "OPENAI_API_KEY not set"}

    task_data = _json.dumps(TASKS, indent=2)
    prompt = LLMPrompt(
        system=(
            "You are a project manager assistant. Given a list of tasks, "
            "write a brief 2-3 sentence status update for the team. "
            "Mention how many tasks are done, in progress, and pending."
        ),
        messages=[
            LLMMessage(role="user", content=f"Tasks:\n{task_data}\n\nRequest: {intent.raw}"),
        ],
        temperature=0.3,
        max_tokens=256,
    )

    response = await llm.generate(prompt)
    return {"summary": response.content, "model": llm.model_name}


@tasks_router.agent_endpoint(
    name="prioritize",
    description="LLM-powered task prioritization advice using a custom prompt",
    intent_scope=IntentScope(allowed_intents=["*"]),
    autonomy_level="manual",  # bypass harness — handler calls LLM directly
)
async def task_prioritize(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Call OpenAI with a custom prioritization prompt."""
    if llm is None:
        return {"error": "OPENAI_API_KEY not set"}

    task_data = _json.dumps(TASKS, indent=2)
    prompt = LLMPrompt(
        system=(
            "You are a project prioritization expert. Given a list of tasks, "
            "recommend which task should be worked on next and why. "
            "Consider priority, current status, and dependencies. Be concise."
        ),
        messages=[
            LLMMessage(role="user", content=f"Tasks:\n{task_data}\n\nRequest: {intent.raw}"),
        ],
        temperature=0.2,
        max_tokens=256,
    )

    response = await llm.generate(prompt)
    return {"recommendation": response.content, "model": llm.model_name}


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Task Tracker Agent (OpenAI)",
    version="0.1.0",
    llm=llm,
    harness=harness,
    tools=tools,
)
app.include_router(tasks_router)
