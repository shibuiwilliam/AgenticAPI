"""Typed Intents example: a support-ticket triage API.

Demonstrates AgenticAPI's most powerful structured-output feature:
**typed intents** (``Intent[TParams]``) where the LLM is constrained
to produce JSON matching a Pydantic schema, and the framework hands
the handler a fully-validated, fully-typed payload.

Where a regular handler accepts ``intent: Intent`` and has to dig
through ``intent.parameters`` for loosely-typed dict values, a typed
handler accepts ``intent: Intent[TicketQuery]`` and gets:

* IDE autocompletion on every field
* Pydantic validation **before** the handler runs (bad LLM output is
  rejected with a clear error)
* Enum / Literal narrowing for free
* Default values for optional fields
* Self-documenting schemas published in the OpenAPI spec

Why a Mock LLM?
    The framework's ``MockBackend`` natively supports the structured
    output protocol used by Anthropic, OpenAI, and Gemini in
    production. By queueing structured responses at startup we get a
    deterministic, dependency-free demo that exercises the *exact*
    same code path as a real LLM. Swap the mock for any real backend
    by changing two lines and adding an API key.

Features demonstrated:

- ``Intent[TicketSearchQuery]`` — typed payloads with enums, literals,
  and constrained ints
- ``Intent[TicketClassification]`` — nested Pydantic models
- ``Intent[EscalationDecision]`` — booleans and explanations
- The same handler shape as untyped intents — no special API to learn
- ``MockBackend.add_structured_response()`` for deterministic demos
- Composition with ``IntentScope`` to gate which intents reach the
  endpoint
- ``follow_up_suggestions`` in the ``AgentResponse`` for multi-turn UX

Run with:
    uvicorn examples.17_typed_intents.app:app --reload

Test with curl:
    # Search tickets — the LLM produces a TicketSearchQuery payload
    # (the mock returns a deterministic "open critical billing" query).
    curl -X POST http://127.0.0.1:8000/agent/tickets.search \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show me all open critical billing tickets from Alice"}'

    # Classify a ticket — the LLM produces a TicketClassification.
    curl -X POST http://127.0.0.1:8000/agent/tickets.classify \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "My payment failed three times today and I need this fixed ASAP"}'

    # Escalation decision — boolean + reason.
    curl -X POST http://127.0.0.1:8000/agent/tickets.should_escalate \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Customer has been waiting for 5 days on a P0 incident"}'

    # Inspect the OpenAPI schema — every typed payload is published.
    curl http://127.0.0.1:8000/openapi.json | python -m json.tool | head -60
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agenticapi import AgenticApp, Intent
from agenticapi.routing import AgentRouter
from agenticapi.runtime.context import AgentContext  # noqa: TC001
from agenticapi.runtime.llm.mock import MockBackend

# Note: ``AgentContext`` is imported at runtime (not under ``TYPE_CHECKING``)
# so that ``typing.get_type_hints()`` on the handler signatures resolves
# successfully. When type hints fail to resolve, the dependency scanner
# falls back to raw string annotations and cannot extract ``T`` from
# ``Intent[T]`` — meaning the framework would not pass the Pydantic schema
# to the LLM and the typed-intent path would silently degrade to keyword
# parsing.


# ---------------------------------------------------------------------------
# 1. Mock data
# ---------------------------------------------------------------------------

TICKETS: list[dict[str, Any]] = [
    {
        "id": "TKT-001",
        "customer": "alice@example.com",
        "category": "billing",
        "priority": "critical",
        "status": "open",
        "summary": "Charged twice for monthly subscription",
        "created_at": "2026-04-09T10:30:00Z",
    },
    {
        "id": "TKT-002",
        "customer": "bob@example.com",
        "category": "technical",
        "priority": "high",
        "status": "in_progress",
        "summary": "API returning 502 on /v2/orders endpoint",
        "created_at": "2026-04-10T14:15:00Z",
    },
    {
        "id": "TKT-003",
        "customer": "alice@example.com",
        "category": "billing",
        "priority": "critical",
        "status": "open",
        "summary": "Refund not received after 7 days",
        "created_at": "2026-04-11T08:00:00Z",
    },
    {
        "id": "TKT-004",
        "customer": "carol@example.com",
        "category": "feature_request",
        "priority": "low",
        "status": "open",
        "summary": "Please add dark mode to the dashboard",
        "created_at": "2026-04-08T16:45:00Z",
    },
]


# ---------------------------------------------------------------------------
# 2. Typed intent schemas — the heart of this example
# ---------------------------------------------------------------------------
#
# Each schema describes a STRUCTURED payload the LLM must produce. The
# framework extracts the schema at endpoint registration time, forwards
# it to the LLM backend (provider-native structured output), validates
# the response, and hands the handler a fully-typed instance.


class TicketStatus(StrEnum):
    """Constrained enum — the LLM is forced to pick one of these."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketCategory(StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    FEATURE_REQUEST = "feature_request"
    ACCOUNT = "account"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketSearchQuery(BaseModel):
    """Filter parameters extracted from a natural-language search."""

    customer: str | None = Field(
        default=None,
        description="Customer email address, or None to search all customers.",
    )
    status: TicketStatus | None = Field(
        default=None,
        description="Status to filter on, or None to include all statuses.",
    )
    priority: TicketPriority | None = Field(
        default=None,
        description="Priority to filter on, or None to include all priorities.",
    )
    category: TicketCategory | None = Field(
        default=None,
        description="Category to filter on, or None to include all categories.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of tickets to return (1-100).",
    )


class TicketClassification(BaseModel):
    """The model's structured opinion on a single ticket description."""

    category: TicketCategory = Field(
        description="The most likely category for this ticket.",
    )
    priority: TicketPriority = Field(
        description="The recommended priority based on urgency signals.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the classification, 0.0 to 1.0.",
    )
    summary: str = Field(
        max_length=120,
        description="A one-line summary of the issue.",
    )
    suggested_owner: str = Field(
        description="Team that should pick this up: 'billing-ops', 'platform-eng', 'product-team', or 'cs-tier-1'.",
    )


class EscalationDecision(BaseModel):
    """Whether the agent recommends escalating to a human, with a reason."""

    should_escalate: bool = Field(
        description="True if a human should be paged, False otherwise.",
    )
    severity: TicketPriority = Field(
        description="Severity level the escalation should be tagged with.",
    )
    reason: str = Field(
        max_length=200,
        description="One-sentence justification for the recommendation.",
    )
    page_oncall: bool = Field(
        default=False,
        description="True if the escalation should page the on-call rotation immediately.",
    )


# ---------------------------------------------------------------------------
# 3. Mock LLM backend with deterministic structured responses
# ---------------------------------------------------------------------------
#
# In production you would do:
#     from agenticapi.runtime.llm import AnthropicBackend
#     llm = AnthropicBackend()  # reads ANTHROPIC_API_KEY
#
# The MockBackend used here implements the same protocol so the
# typed-intent code path is identical. We queue one structured response
# per endpoint call so the demo is reproducible.

mock_llm = MockBackend()

# Response for /agent/tickets.search
mock_llm.add_structured_response(
    {
        "customer": "alice@example.com",
        "status": "open",
        "priority": "critical",
        "category": "billing",
        "limit": 10,
    }
)

# Response for /agent/tickets.classify
mock_llm.add_structured_response(
    {
        "category": "billing",
        "priority": "critical",
        "confidence": 0.92,
        "summary": "Repeated payment failures — needs urgent investigation.",
        "suggested_owner": "billing-ops",
    }
)

# Response for /agent/tickets.should_escalate
mock_llm.add_structured_response(
    {
        "should_escalate": True,
        "severity": "critical",
        "reason": "P0 incident open for 5 days exceeds the 24h SLA — page on-call.",
        "page_oncall": True,
    }
)


# ---------------------------------------------------------------------------
# 4. App + endpoints
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Support Ticket Triage (Typed Intents demo)",
    version="0.1.0",
    llm=mock_llm,
)

tickets = AgentRouter(prefix="tickets", tags=["tickets"])


def _require_params(intent: Intent[Any]) -> Any:
    """Narrow ``intent.params`` from ``T | None`` to ``T``.

    When a handler declares ``Intent[SomeModel]`` the framework guarantees
    ``intent.params`` is populated with a validated instance by the time
    the handler runs (either the LLM produced a schema-conforming payload,
    or the request was rejected with a parse error before the handler was
    ever called). This tiny helper documents that invariant at the call
    site and narrows the type for mypy users without scattering ``cast``
    calls through every handler.
    """
    if intent.params is None:
        # Defence in depth: if the framework invariant is ever broken, fail
        # loudly with a clear message rather than silently returning junk.
        raise RuntimeError(
            "typed-intent handler invoked without a validated payload — "
            "this should never happen when Intent[T] is used correctly",
        )
    return intent.params


@tickets.agent_endpoint(
    name="search",
    description="Search support tickets with structured filters extracted from natural language.",
    autonomy_level="auto",
)
async def search_tickets(
    intent: Intent[TicketSearchQuery],
    context: AgentContext,
) -> dict[str, Any]:
    """The handler receives a fully-typed, validated query payload.

    No more digging through ``intent.parameters`` and casting strings.
    The IDE knows that ``query.priority`` is a ``TicketPriority`` enum
    and ``query.limit`` is an ``int`` between 1 and 100.
    """
    query: TicketSearchQuery = _require_params(intent)

    matches = TICKETS
    if query.customer:
        matches = [t for t in matches if t["customer"] == query.customer]
    if query.status:
        matches = [t for t in matches if t["status"] == query.status]
    if query.priority:
        matches = [t for t in matches if t["priority"] == query.priority]
    if query.category:
        matches = [t for t in matches if t["category"] == query.category]
    matches = matches[: query.limit]

    return {
        "query": query.model_dump(),
        "matches": matches,
        "count": len(matches),
        "raw_intent": intent.raw,
    }


@tickets.agent_endpoint(
    name="classify",
    description="Classify a free-text ticket description into category, priority, and owner.",
    autonomy_level="auto",
)
async def classify_ticket(
    intent: Intent[TicketClassification],
    context: AgentContext,
) -> dict[str, Any]:
    """Classification endpoint — turns a customer's complaint into a
    structured triage decision.

    Notice the handler signature: it declares the SAME shape as the
    search handler. The only difference is the schema parameter, and
    the framework forwards it to the LLM at runtime.
    """
    classification: TicketClassification = _require_params(intent)
    return {
        "classification": classification.model_dump(),
        "routed_to": classification.suggested_owner,
        "needs_immediate_attention": classification.priority in (TicketPriority.HIGH, TicketPriority.CRITICAL),
        "received_at": datetime.now(UTC).isoformat(),
    }


@tickets.agent_endpoint(
    name="should_escalate",
    description="Decide whether a ticket requires human escalation, with reasoning.",
    autonomy_level="auto",
)
async def should_escalate(
    intent: Intent[EscalationDecision],
    context: AgentContext,
) -> dict[str, Any]:
    """Boolean-with-reason pattern: a yes/no plus structured justification.

    Useful for any "should we do X?" decision the agent makes — the
    framework guarantees the model returned valid fields, so the
    handler can branch on ``decision.should_escalate`` with full
    confidence.
    """
    decision: EscalationDecision = _require_params(intent)

    next_steps: list[str] = []
    if decision.should_escalate:
        next_steps.append(f"Create escalation record at severity={decision.severity}")
        if decision.page_oncall:
            next_steps.append("Page on-call rotation via PagerDuty")
        next_steps.append("Notify customer that escalation is in progress")
    else:
        next_steps.append("Continue working the ticket on the standard queue")

    return {
        "decision": decision.model_dump(),
        "next_steps": next_steps,
    }


app.include_router(tickets)
