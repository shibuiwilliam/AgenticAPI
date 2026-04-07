"""Google Gemini powered agent example with harness safety.

Demonstrates:
- GeminiBackend for LLM-powered intent parsing and code generation
- HarnessEngine with CodePolicy and DataPolicy
- DatabaseTool and CacheTool for agent-generated code
- Session management for multi-turn conversations
- Full pipeline: intent -> code generation -> policy check -> sandbox -> response

Prerequisites:
    export GOOGLE_API_KEY="AIza..."

Run with:
    uvicorn examples.05_gemini_agent.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.05_gemini_agent.app:app

Test with curl:
    # List open tickets
    curl -X POST http://127.0.0.1:8000/agent/tickets.search \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show me all open critical tickets"}'

    # Get support metrics
    curl -X POST http://127.0.0.1:8000/agent/tickets.metrics \
        -H "Content-Type: application/json" \
        -d '{"intent": "What is the average resolution time by severity?"}'

    # Multi-turn with session
    curl -X POST http://127.0.0.1:8000/agent/tickets.search \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show billing tickets", "session_id": "sess1"}'

    curl -X POST http://127.0.0.1:8000/agent/tickets.search \
        -H "Content-Type: application/json" \
        -d '{"intent": "Which of those are still unresolved?", "session_id": "sess1"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi.app import AgenticApp
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.interface.intent import Intent, IntentScope
from agenticapi.interface.response import AgentResponse
from agenticapi.routing import AgentRouter
from agenticapi.runtime.llm.gemini import GeminiBackend
from agenticapi.runtime.tools.cache import CacheTool
from agenticapi.runtime.tools.database import DatabaseTool
from agenticapi.runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# Mock data — a support ticket system
# ---------------------------------------------------------------------------

TICKETS = [
    {
        "id": 101,
        "subject": "Login failure",
        "category": "auth",
        "severity": "critical",
        "status": "open",
        "assignee": "Yuki",
        "hours_to_resolve": None,
    },
    {
        "id": 102,
        "subject": "Slow dashboard load",
        "category": "performance",
        "severity": "high",
        "status": "in_progress",
        "assignee": "Kenji",
        "hours_to_resolve": None,
    },
    {
        "id": 103,
        "subject": "Billing overcharge",
        "category": "billing",
        "severity": "high",
        "status": "resolved",
        "assignee": "Yuki",
        "hours_to_resolve": 4.5,
    },
    {
        "id": 104,
        "subject": "Password reset email not sent",
        "category": "auth",
        "severity": "medium",
        "status": "resolved",
        "assignee": "Mika",
        "hours_to_resolve": 1.2,
    },
    {
        "id": 105,
        "subject": "API rate limit too low",
        "category": "api",
        "severity": "low",
        "status": "open",
        "assignee": "Kenji",
        "hours_to_resolve": None,
    },
    {
        "id": 106,
        "subject": "Invoice PDF broken",
        "category": "billing",
        "severity": "critical",
        "status": "open",
        "assignee": "Mika",
        "hours_to_resolve": None,
    },
    {
        "id": 107,
        "subject": "Typo on pricing page",
        "category": "content",
        "severity": "low",
        "status": "resolved",
        "assignee": "Sato",
        "hours_to_resolve": 0.5,
    },
    {
        "id": 108,
        "subject": "SSO integration error",
        "category": "auth",
        "severity": "high",
        "status": "in_progress",
        "assignee": "Yuki",
        "hours_to_resolve": None,
    },
    {
        "id": 109,
        "subject": "Export CSV timeout",
        "category": "performance",
        "severity": "medium",
        "status": "resolved",
        "assignee": "Kenji",
        "hours_to_resolve": 6.0,
    },
    {
        "id": 110,
        "subject": "Webhook delivery failures",
        "category": "api",
        "severity": "critical",
        "status": "in_progress",
        "assignee": "Sato",
        "hours_to_resolve": None,
    },
]


async def mock_db_execute(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Simulate database queries against the ticket table."""
    q = query.lower()
    if "ticket" in q or "support" in q:
        return TICKETS
    return []


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

db_tool = DatabaseTool(
    name="ticket_db",
    description=(
        "Support ticket database with a 'tickets' table. "
        "Columns: id (int), subject (str), category (str), severity (str: critical/high/medium/low), "
        "status (str: open/in_progress/resolved), assignee (str), hours_to_resolve (float or null)."
    ),
    execute_fn=mock_db_execute,
    read_only=True,
)

cache_tool = CacheTool(
    name="ticket_cache",
    description="Cache for frequently queried ticket data",
    default_ttl_seconds=60,
)

tools = ToolRegistry()
tools.register(db_tool)
tools.register(cache_tool)

# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

code_policy = CodePolicy(
    denied_modules=["os", "subprocess", "shutil", "sys", "importlib"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
    allow_network=False,
    max_code_lines=200,
)

data_policy = DataPolicy(
    readable_tables=["tickets"],
    writable_tables=["tickets"],
    restricted_columns=["customer_email", "internal_notes"],
    deny_ddl=True,
    max_result_rows=500,
)

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

harness = HarnessEngine(
    policies=[code_policy, data_policy],
)

# ---------------------------------------------------------------------------
# LLM backend — Google Gemini
# ---------------------------------------------------------------------------

llm = GeminiBackend(model="gemini-2.5-flash")

# ---------------------------------------------------------------------------
# Routers and endpoints
# ---------------------------------------------------------------------------

tickets_router = AgentRouter(prefix="tickets", tags=["support"])


@tickets_router.agent_endpoint(
    name="search",
    description="Search and filter support tickets by category, severity, status, or assignee",
    intent_scope=IntentScope(allowed_intents=["ticket.*", "support.*", "*.read", "*.analyze", "*.clarify"]),
    autonomy_level="auto",
)
async def ticket_search(intent: Intent, context: AgentContext) -> AgentResponse:
    """Search tickets with optional filters."""
    category = intent.parameters.get("category")
    severity = intent.parameters.get("severity")
    status = intent.parameters.get("status")

    results = TICKETS
    if category:
        results = [t for t in results if t["category"] == category]
    if severity:
        results = [t for t in results if t["severity"] == severity]
    if status:
        results = [t for t in results if t["status"] == status]

    return AgentResponse(
        result={
            "tickets": results,
            "count": len(results),
        },
        reasoning=f"Filtered {len(TICKETS)} tickets to {len(results)} results",
    )


@tickets_router.agent_endpoint(
    name="metrics",
    description="Support metrics: resolution times, ticket distribution, workload per assignee",
    intent_scope=IntentScope(allowed_intents=["ticket.*", "support.*", "*.read", "*.analyze", "*.clarify"]),
    autonomy_level="auto",
)
async def ticket_metrics(intent: Intent, context: AgentContext) -> AgentResponse:
    """Compute support team metrics."""
    total = len(TICKETS)
    open_count = sum(1 for t in TICKETS if t["status"] == "open")
    in_progress = sum(1 for t in TICKETS if t["status"] == "in_progress")
    resolved = sum(1 for t in TICKETS if t["status"] == "resolved")

    resolved_tickets = [t for t in TICKETS if t["hours_to_resolve"] is not None]
    avg_resolution = (
        round(sum(t["hours_to_resolve"] for t in resolved_tickets) / len(resolved_tickets), 1)
        if resolved_tickets
        else 0
    )

    by_severity: dict[str, int] = {}
    for t in TICKETS:
        by_severity[t["severity"]] = by_severity.get(t["severity"], 0) + 1

    by_assignee: dict[str, dict[str, int]] = {}
    for t in TICKETS:
        name = t["assignee"]
        by_assignee.setdefault(name, {"open": 0, "in_progress": 0, "resolved": 0})
        by_assignee[name][t["status"]] += 1

    return AgentResponse(
        result={
            "summary": {
                "total": total,
                "open": open_count,
                "in_progress": in_progress,
                "resolved": resolved,
                "avg_resolution_hours": avg_resolution,
            },
            "by_severity": by_severity,
            "by_assignee": by_assignee,
        },
        reasoning=f"Support metrics across {total} tickets, avg resolution {avg_resolution}h",
    )


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Support Ticket Agent (Google Gemini)",
    version="0.1.0",
    llm=llm,  # type: ignore[arg-type]
    harness=harness,
    tools=tools,
)
app.include_router(tickets_router)
