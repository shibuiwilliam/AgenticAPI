# Budgets & Cost Governance

`BudgetPolicy` exists, is tested, and is useful today, but it is important to describe it accurately:

- It is a real policy type under `harness/policy/budget_policy.py`.
- It is not automatically wired around every stock LLM call in the default `AgenticApp` plus `HarnessEngine` path.
- Its main runtime entry points are `estimate_and_enforce(...)` and `record_actual(...)`, not `PolicyEvaluator.evaluate(...)`.

This document describes the implementation as it exists in the current tree.

## What BudgetPolicy Actually Does

`BudgetPolicy` provides cost-governance primitives for four scopes:

1. Per request
2. Per session
3. Per user per day
4. Per endpoint per day

It uses a `PricingRegistry` to estimate LLM cost from token counts and a `SpendStore` to track accumulated actual spend.

Primary file:

- `src/agenticapi/harness/policy/budget_policy.py`

## Current Integration Reality

The current implementation is split into three layers:

### 1. Policy type

`BudgetPolicy` subclasses `Policy`, so it can live beside `CodePolicy`, `DataPolicy`, `ResourcePolicy`, and `RuntimePolicy`.

### 2. Explicit cost API

Real budget behavior lives here:

- `BudgetPolicy.estimate_and_enforce(ctx)`
- `BudgetPolicy.record_actual(ctx, actual_input_tokens=..., actual_output_tokens=...)`
- `BudgetPolicy.current_spend(...)`

### 3. Compatibility stub

`BudgetPolicy.evaluate(...)` intentionally returns an allow result and does not enforce cost ceilings by itself. That method exists so `BudgetPolicy` can still sit inside `HarnessEngine(policies=[...])` without breaking the generic policy pipeline.

Practical consequence:

- `HarnessEngine(policies=[BudgetPolicy(...)])` is not enough, by itself, to guarantee end-to-end budget enforcement in the stock request path.
- Budgeting must currently be wired explicitly around LLM calls, as shown in `examples/15_budget_policy/app.py`.

## PricingRegistry

`PricingRegistry` maps model IDs to per-1k-token pricing.

```python
from agenticapi import PricingRegistry

pricing = PricingRegistry.default()
cost = pricing.estimate_cost(
    model="claude-sonnet-4-6",
    input_tokens=1500,
    output_tokens=800,
)
```

Important details:

- Costs are stored as `float`, not `Decimal`.
- The current default registry includes built-in provider models plus a zero-cost mock model.
- The default registry is a snapshot, not a live pricing feed.

## BudgetPolicy Constructor

The current parameter names are:

```python
from agenticapi import BudgetPolicy, PricingRegistry

budget = BudgetPolicy(
    pricing=PricingRegistry.default(),
    max_per_request_usd=0.50,
    max_per_session_usd=5.00,
    max_per_user_per_day_usd=50.00,
    max_per_endpoint_per_day_usd=500.00,
)
```

The older names below are stale and should not be reintroduced:

- `max_cost_per_request_usd`
- `max_cost_per_session_usd`
- `max_cost_per_user_usd`

## SpendStore

`SpendStore` is a small synchronous protocol:

```python
class SpendStore(Protocol):
    def get(self, scope: str, key: str, *, day: date | None = None) -> float: ...
    def add(self, scope: str, key: str, amount_usd: float, *, day: date | None = None) -> None: ...
    def reset(self, scope: str, key: str | None = None) -> None: ...
```

Notes:

- The shipped store is `InMemorySpendStore`.
- It is process-local.
- It keys daily totals by `date`, not by a rolling 24-hour window.
- Production multi-process deployments need a shared store implementation.

## Enforcement Flow

The current cost flow is:

1. Build a `BudgetEvaluationContext`.
2. Call `estimate_and_enforce(ctx)` before the LLM request.
3. Make the LLM call.
4. Call `record_actual(ctx, actual_input_tokens=..., actual_output_tokens=...)` after the response.

Example:

```python
from agenticapi import BudgetPolicy, PricingRegistry
from agenticapi.harness.policy.budget_policy import BudgetEvaluationContext

pricing = PricingRegistry.default()
budget = BudgetPolicy(
    pricing=pricing,
    max_per_request_usd=0.05,
    max_per_session_usd=1.00,
)

ctx = BudgetEvaluationContext(
    endpoint_name="chat.ask",
    session_id="alice-001",
    user_id="alice",
    model="mock",
    input_tokens=120,
    max_output_tokens=256,
)

budget.estimate_and_enforce(ctx)
# response = await llm.generate(prompt)
# budget.record_actual(
#     ctx,
#     actual_input_tokens=response.usage.input_tokens,
#     actual_output_tokens=response.usage.output_tokens,
# )
```

Important nuance:

- `estimate_and_enforce(...)` checks projected spend using current recorded totals plus a worst-case estimate.
- It does not reserve the estimate in the store.
- `record_actual(...)` appends actual spend after the call returns.

## Exceptions

Budget violations raise `BudgetExceeded`, which maps to HTTP 402.

The current scope values used by the implementation are:

- `"request"`
- `"session"`
- `"user_per_day"`
- `"endpoint_per_day"`

## Observability

The metrics helper `record_budget_block(scope=...)` exists, but budget metrics are not emitted automatically from every path yet. New budget-aware flows should record budget blocks explicitly.

## Tests And Example

Reference points in the current tree:

- `tests/unit/harness/policy/test_budget_policy.py`
- `examples/15_budget_policy/app.py`

The example is the best source for how to integrate `BudgetPolicy` today because it shows the explicit call pattern the stock request path does not yet provide automatically.
