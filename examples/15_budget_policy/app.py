"""Budget policy example: cost governance for agent endpoints.

Demonstrates ``BudgetPolicy`` — the cost-governance arm of the
AgenticAPI harness. Real-money agent systems need hard ceilings on
per-request, per-session, per-user, and per-endpoint spending, and
this example shows the full lifecycle:

    pre-call estimate -> enforcement -> LLM call -> post-call reconciliation

The app models a small chat assistant with three endpoints that
share a single ``BudgetPolicy``. Each endpoint uses ``BudgetPolicy``
the way a real app would:

1. **Pre-call estimate** — before we "call the LLM" the endpoint
   asks the policy to check the projected cost against every budget
   scope. If any ceiling would be breached, the policy raises
   :class:`BudgetExceeded` which maps to HTTP **402 Payment Required**.
2. **LLM call** — this example uses a mock LLM that returns a fixed
   token count, so you can run it without any API keys and see
   deterministic cost numbers.
3. **Post-call reconciliation** — after the mock LLM returns, the
   endpoint calls ``record_actual`` so subsequent requests see the
   higher running totals.

Features demonstrated:

* **BudgetPolicy** with all four scopes configured at once
* **PricingRegistry.default()** ships public list prices for every
  AgenticAPI-supported model; custom models added via ``set()``
* **InMemorySpendStore** for process-local running totals
* **BudgetExceeded -> HTTP 402** automatic status mapping
* **Scope inspection** via ``current_spend()`` — handy for billing
  dashboards, alerts, and this example's ``/budget/status`` endpoint
* **Composition with other policies** — ``BudgetPolicy`` is a regular
  ``Policy`` so it passes through ``PolicyEvaluator`` alongside
  ``CodePolicy`` without any special wiring
* **Graceful error responses** — handlers catch ``BudgetExceeded``,
  return structured JSON with the offending scope, limit, and
  observed spend, and let the framework map to 402
* **Manual spend reset** — ``/budget/reset`` clears the store for
  demo runs (wired directly to ``spend_store.reset``)

No LLM or API key is required. The example uses a deterministic mock
LLM so you can reproduce every budget breach by replaying the curl
commands in the docstring.

Run with::

    uvicorn examples.15_budget_policy.app:app --reload

Or using the CLI::

    agenticapi dev --app examples.15_budget_policy.app:app

Walkthrough::

    # 1. Check initial budget status (everything is $0.0000)
    curl -X POST http://127.0.0.1:8000/agent/budget.status \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show current spend"}'

    # 2. Ask a small question — fits comfortably in all budgets
    curl -X POST http://127.0.0.1:8000/agent/chat.ask \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "What is AgenticAPI?", "session_id": "alice-001"}'

    # 3. Ask a large question — single call hits the per-request ceiling
    curl -X POST http://127.0.0.1:8000/agent/chat.research \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Write a 10-page report", "session_id": "alice-001"}'
    # -> HTTP 402, scope=request, explains the breach in the JSON body

    # 4. Drain the per-session budget with a few small calls
    for i in 1 2 3 4 5 6; do
        curl -X POST http://127.0.0.1:8000/agent/chat.ask \\
            -H "Content-Type: application/json" \\
            -d '{"intent": "Hello", "session_id": "bob-001"}'
    done
    # -> first few succeed, then HTTP 402 with scope=session

    # 5. Check the spend so far
    curl -X POST http://127.0.0.1:8000/agent/budget.status \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show spend", "session_id": "bob-001"}'

    # 6. Reset for the next demo run
    curl -X POST http://127.0.0.1:8000/agent/budget.reset \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "reset"}'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi import (
    AgenticApp,
    AgentResponse,
    BudgetPolicy,
    CodePolicy,
    HarnessEngine,
    Intent,
)
from agenticapi.exceptions import BudgetExceeded
from agenticapi.harness.policy.budget_policy import (
    BudgetEvaluationContext,
    InMemorySpendStore,
)
from agenticapi.harness.policy.pricing import PricingRegistry
from agenticapi.routing import AgentRouter

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# 1. Pricing registry
# ---------------------------------------------------------------------------
# Start from the default public-price snapshot and layer a custom
# fine-tuned model on top. Real deployments would load contract prices
# from config or a database here.

pricing = PricingRegistry.default()
pricing.set(
    "my-finetuned-claude",
    input_usd_per_1k=4.50,
    output_usd_per_1k=20.00,
)


# ---------------------------------------------------------------------------
# 2. Shared spend store
# ---------------------------------------------------------------------------
# In production this would be a Redis/DB-backed implementation of the
# ``SpendStore`` protocol, shared across every process behind the load
# balancer. For the demo, a single in-memory store keyed by scope is
# plenty and is also exposed so the ``/budget/reset`` endpoint can
# clear it.

spend_store = InMemorySpendStore()


# ---------------------------------------------------------------------------
# 3. Budget policy — every scope at once
# ---------------------------------------------------------------------------
# The numbers are deliberately small so the demo breaches them with a
# single curl loop. Production numbers would depend on your contract,
# typical request cost, and tolerance for drift.

budget = BudgetPolicy(
    pricing=pricing,
    max_per_request_usd=0.10,  # one call: never more than 10 cents
    max_per_session_usd=0.30,  # one session: never more than 30 cents total
    max_per_user_per_day_usd=2.00,  # one user per day: $2 ceiling
    max_per_endpoint_per_day_usd=10.00,  # one endpoint per day: $10 ceiling
    spend_store=spend_store,
)


# ---------------------------------------------------------------------------
# 4. Harness — BudgetPolicy composes with other policies cleanly
# ---------------------------------------------------------------------------

code_policy = CodePolicy(
    denied_modules=["os", "subprocess", "sys"],
    deny_eval_exec=True,
)

harness = HarnessEngine(policies=[code_policy, budget])


# ---------------------------------------------------------------------------
# 5. Mock LLM costing
# ---------------------------------------------------------------------------
# Two token "profiles" the endpoints pick between. The exact numbers
# are chosen so the sample curl walkthrough in the docstring produces
# a deterministic sequence of allow / 402 responses.

_MODEL = "gpt-4o-mini"  # cheap, predictable pricing for the demo


class _FakeLLMCall:
    """Deterministic stand-in for an LLM call.

    Real endpoints would call ``AnthropicBackend.generate()`` here.
    The example uses a fake so the budget numbers stay the same run
    to run, no API key required, no cost incurred.
    """

    def __init__(self, *, input_tokens: int, output_tokens: int, answer: str) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.answer = answer

    async def call(self) -> tuple[str, int, int]:
        return self.answer, self.input_tokens, self.output_tokens


_SMALL = _FakeLLMCall(
    input_tokens=200,
    output_tokens=50,
    answer="Here's a short answer.",
)
_LARGE = _FakeLLMCall(
    input_tokens=2_000,
    output_tokens=800,
    answer="Here's a much longer, research-grade answer with many citations...",
)


# ---------------------------------------------------------------------------
# 6. Endpoint helper: run the pre/post budget dance
# ---------------------------------------------------------------------------
# Wrapping the pre-call + LLM call + post-call in one async helper keeps
# the actual endpoints tiny. Real apps would factor this into a base
# class or middleware stage.


async def _run_with_budget(
    *,
    endpoint_name: str,
    session_id: str | None,
    user_id: str | None,
    llm_call: _FakeLLMCall,
    max_output_tokens: int,
) -> dict[str, Any]:
    """Gate a fake LLM call through ``BudgetPolicy``.

    Mirrors what the framework would do for you if you used the full
    harness pipeline with ``autonomy_level="auto"``; here we run it
    explicitly to make the three-step lifecycle visible.
    """
    ctx = BudgetEvaluationContext(
        endpoint_name=endpoint_name,
        session_id=session_id,
        user_id=user_id,
        model=_MODEL,
        input_tokens=llm_call.input_tokens,
        max_output_tokens=max_output_tokens,
    )

    # Pre-call: may raise BudgetExceeded -> HTTP 402
    estimate = budget.estimate_and_enforce(ctx)

    # The "LLM call" itself — deterministic for the demo.
    answer, actual_input, actual_output = await llm_call.call()

    # Post-call reconciliation — update the running totals so the
    # next request in the same scopes sees the higher number.
    actual_cost = budget.record_actual(
        ctx,
        actual_input_tokens=actual_input,
        actual_output_tokens=actual_output,
    )

    return {
        "answer": answer,
        "model": _MODEL,
        "estimated_cost_usd": round(estimate.estimated_cost_usd, 4),
        "actual_cost_usd": round(actual_cost, 4),
        "tokens": {
            "input": actual_input,
            "output": actual_output,
        },
    }


# ---------------------------------------------------------------------------
# 7. Application
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Budget Policy Example",
    version="0.1.0",
    description="Cost-governance demo using BudgetPolicy + PricingRegistry",
    harness=harness,
)


# ---------------------------------------------------------------------------
# 8. Chat endpoints — every request goes through BudgetPolicy
# ---------------------------------------------------------------------------

chat = AgentRouter(prefix="chat", tags=["chat"])


@chat.agent_endpoint(
    name="ask",
    description="Ask a short question (small token budget)",
    autonomy_level="auto",
)
async def chat_ask(intent: Intent, context: AgentContext) -> AgentResponse:
    """Small-prompt endpoint that always fits in a single per-request budget.

    Running this in a loop is the fastest way to drain the
    ``max_per_session_usd`` ceiling and see a 402.
    """
    try:
        result = await _run_with_budget(
            endpoint_name="chat.ask",
            session_id=context.session_id,
            user_id=context.user_id or "anonymous",
            llm_call=_SMALL,
            max_output_tokens=80,
        )
    except BudgetExceeded as exc:
        return _budget_exceeded_response(exc)
    return AgentResponse(
        result={"intent": intent.raw, **result},
        reasoning="Small LLM call, checked against all budget scopes",
    )


@chat.agent_endpoint(
    name="research",
    description="Deep-research question (large token budget)",
    autonomy_level="auto",
)
async def chat_research(intent: Intent, context: AgentContext) -> AgentResponse:
    """Large-prompt endpoint that breaches ``max_per_request_usd`` in one shot.

    This is the "runaway prompt injection" simulation — a single call
    that would cost more than the per-request ceiling gets blocked
    before the LLM is ever contacted.
    """
    try:
        result = await _run_with_budget(
            endpoint_name="chat.research",
            session_id=context.session_id,
            user_id=context.user_id or "anonymous",
            llm_call=_LARGE,
            max_output_tokens=1_200,  # aggressive output ceiling
        )
    except BudgetExceeded as exc:
        return _budget_exceeded_response(exc)
    return AgentResponse(
        result={"intent": intent.raw, **result},
        reasoning="Large LLM call, checked against all budget scopes",
    )


# ---------------------------------------------------------------------------
# 9. Budget-inspection endpoints
# ---------------------------------------------------------------------------

inspect = AgentRouter(prefix="budget", tags=["budget"])


@inspect.agent_endpoint(
    name="status",
    description="Current spend across every configured scope",
    autonomy_level="auto",
)
async def budget_status(intent: Intent, context: AgentContext) -> AgentResponse:
    """Return the running spend per scope.

    Inspection helpers like this one are how operators wire the policy
    into a billing dashboard, an SRE alert, or a per-tenant usage page.
    """
    session_id = context.session_id
    user_id = context.user_id or "anonymous"

    status: dict[str, Any] = {
        "limits": {
            "per_request_usd": budget.max_per_request_usd,
            "per_session_usd": budget.max_per_session_usd,
            "per_user_per_day_usd": budget.max_per_user_per_day_usd,
            "per_endpoint_per_day_usd": budget.max_per_endpoint_per_day_usd,
        },
        "current_spend_usd": {
            "this_session": (round(budget.current_spend(scope="session", key=session_id), 4) if session_id else None),
            "this_user_today": round(budget.current_spend(scope="user_per_day", key=user_id), 4),
            "chat_ask_today": round(budget.current_spend(scope="endpoint_per_day", key="chat.ask"), 4),
            "chat_research_today": round(budget.current_spend(scope="endpoint_per_day", key="chat.research"), 4),
        },
        "model": _MODEL,
        "session_id": session_id,
        "user_id": user_id,
    }
    return AgentResponse(
        result=status,
        reasoning="Read-only view of the BudgetPolicy spend store",
    )


@inspect.agent_endpoint(
    name="reset",
    description="Reset all running totals (demo only)",
    autonomy_level="auto",
)
async def budget_reset(intent: Intent, context: AgentContext) -> AgentResponse:
    """Clear the in-memory spend store.

    In production you would almost never do this — day-scoped budgets
    roll over naturally at midnight UTC, and session budgets go away
    with the session. It exists here so you can re-run the demo
    without restarting the server.
    """
    for scope in ("session", "user_per_day", "endpoint_per_day"):
        spend_store.reset(scope)
    return AgentResponse(
        result={"status": "cleared", "scopes": ["session", "user_per_day", "endpoint_per_day"]},
        reasoning="InMemorySpendStore reset for the demo",
    )


# ---------------------------------------------------------------------------
# 10. Error helper
# ---------------------------------------------------------------------------


def _budget_exceeded_response(exc: BudgetExceeded) -> AgentResponse:
    """Format a ``BudgetExceeded`` as a structured ``AgentResponse``.

    Framework users who don't catch the exception manually will see
    the framework map ``BudgetExceeded`` -> HTTP 402 automatically.
    This example catches it in the handler so the demo can return
    the same 200-wrapper shape while still preserving the scope,
    observed and limit figures in the response body. That makes the
    curl walkthrough easier to read.
    """
    return AgentResponse(
        result={
            "ok": False,
            "error": "budget_exceeded",
            "scope": exc.scope,
            "limit_usd": exc.limit_usd,
            "observed_usd": round(exc.observed_usd, 4),
            "model": exc.model,
        },
        status="error",
        reasoning=f"BudgetPolicy refused the call: {exc.scope} budget breached",
        error=str(exc),
    )


# ---------------------------------------------------------------------------
# 11. Wire routers
# ---------------------------------------------------------------------------

app.include_router(chat)
app.include_router(inspect)
