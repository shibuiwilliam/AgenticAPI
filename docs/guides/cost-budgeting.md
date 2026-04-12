# Cost Budgeting

LLM calls cost money, so AgenticAPI ships a real cost-governance primitive: `BudgetPolicy`.

The important caveat is current integration scope:

!!! note
    `BudgetPolicy` is implemented and tested, but it is not yet automatically wired around every stock `AgenticApp` plus `HarnessEngine` LLM call. Treat it as an explicit integration pattern today.

## The Pieces

| Component | Purpose |
|---|---|
| `PricingRegistry` | Per-model token pricing |
| `BudgetPolicy` | Enforces request/session/user/endpoint spend ceilings |
| `SpendStore` | Tracks accumulated actual spend |
| `BudgetEvaluationContext` | Carries endpoint, session, user, model, and token-estimate context |
| `BudgetExceeded` | Exception raised on violation |

## Current Integration Pattern

The current pattern is explicit:

1. Build a `BudgetEvaluationContext`
2. Call `budget.estimate_and_enforce(ctx)` before the LLM call
3. Make the LLM request
4. Call `budget.record_actual(...)` with real token usage

```python
from agenticapi import AgentResponse, AgenticApp, BudgetPolicy, Intent, PricingRegistry
from agenticapi.harness.policy.budget_policy import BudgetEvaluationContext
from agenticapi.runtime.context import AgentContext
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.llm.mock import MockBackend

app = AgenticApp(title="budgeted")
llm = MockBackend(responses=["AgenticAPI is a harnessed agent framework for Python."])
budget = BudgetPolicy(
    pricing=PricingRegistry.default(),
    max_per_request_usd=0.05,
    max_per_session_usd=1.00,
    max_per_user_per_day_usd=10.00,
)


@app.agent_endpoint(name="chat.ask")
async def chat(intent: Intent, context: AgentContext) -> AgentResponse:
    prompt = LLMPrompt(
        system="Answer briefly.",
        messages=[LLMMessage(role="user", content=intent.raw)],
        max_tokens=256,
    )
    budget_ctx = BudgetEvaluationContext(
        endpoint_name="chat.ask",
        session_id=context.session_id,
        user_id=context.user_id,
        model=llm.model_name,
        input_tokens=max(1, len(intent.raw) // 4),
        max_output_tokens=prompt.max_tokens,
    )

    budget.estimate_and_enforce(budget_ctx)
    response = await llm.generate(prompt)
    budget.record_actual(
        budget_ctx,
        actual_input_tokens=response.usage.input_tokens,
        actual_output_tokens=response.usage.output_tokens,
    )

    return AgentResponse(result={"answer": response.content})
```

## Constructor Parameters

The current parameter names are:

```python
budget = BudgetPolicy(
    pricing=PricingRegistry.default(),
    max_per_request_usd=0.05,
    max_per_session_usd=1.00,
    max_per_user_per_day_usd=10.00,
    max_per_endpoint_per_day_usd=500.00,
)
```

## PricingRegistry

`PricingRegistry` estimates cost from model ID plus token counts:

```python
pricing = PricingRegistry.default()
cost = pricing.estimate_cost(
    model="claude-sonnet-4-6",
    input_tokens=1500,
    output_tokens=800,
)
print(f"${cost:.4f}")
```

It is a snapshot, not a live pricing feed. Override or extend it when vendor pricing changes.

## Budget Scopes

`BudgetPolicy` can enforce up to four scopes:

| Parameter | Scope |
|---|---|
| `max_per_request_usd` | Single call |
| `max_per_session_usd` | Shared `session_id` |
| `max_per_user_per_day_usd` | Shared `user_id` for the current UTC day |
| `max_per_endpoint_per_day_usd` | Shared endpoint name for the current UTC day |

## SpendStore

The default store is `InMemorySpendStore`.

Use a custom `SpendStore` when you need shared state across processes or hosts. The current protocol is synchronous:

```python
class SpendStore(Protocol):
    def get(self, scope: str, key: str, *, day: date | None = None) -> float: ...
    def add(self, scope: str, key: str, amount_usd: float, *, day: date | None = None) -> None: ...
    def reset(self, scope: str, key: str | None = None) -> None: ...
```

## Important Behavior Notes

- `estimate_and_enforce(...)` checks projected spend using current recorded totals plus a worst-case estimate.
- It does not reserve budget in the store.
- `record_actual(...)` adds actual spend after the LLM response returns.
- `BudgetPolicy.evaluate(...)` is intentionally a compatibility stub; it does not perform the real budget logic by itself.

## Inspecting Current Spend

```python
spend = budget.current_spend(scope="session", key="alice-001")
print(f"${spend:.2f}")
```

## Exceptions

Violations raise `BudgetExceeded`. The framework maps that exception to HTTP 402.

## Observability

The helper `record_budget_block(scope=...)` exists, but budget metrics are not emitted automatically from every execution path yet. If you build a custom budget-aware flow, record budget blocks explicitly.

## Runnable Example

See [`examples/15_budget_policy/app.py`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/15_budget_policy). That example shows the current recommended integration pattern more accurately than older docs that implied stock-harness automation.

## Known Limitations

- The default store is process-local.
- There is no built-in multi-host spend store.
- Provider pricing must be updated manually.
- Stock request-path integration is still explicit, not automatic.
