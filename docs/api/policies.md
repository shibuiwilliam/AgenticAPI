# Policies

## Policy (Base)

::: agenticapi.harness.policy.base.Policy

## PolicyResult

::: agenticapi.harness.policy.base.PolicyResult

## CodePolicy

::: agenticapi.harness.policy.code_policy.CodePolicy

## DataPolicy

::: agenticapi.harness.policy.data_policy.DataPolicy

## ResourcePolicy

::: agenticapi.harness.policy.resource_policy.ResourcePolicy

## RuntimePolicy

::: agenticapi.harness.policy.runtime_policy.RuntimePolicy

## BudgetPolicy

Cost-governance primitive with per-request, per-session, per-user-per-day, and per-endpoint-per-day scopes.

In the current implementation, the real budget logic lives in `estimate_and_enforce(...)` and `record_actual(...)`. See the guide for the current explicit integration pattern.

See the [Cost Budgeting guide](../guides/cost-budgeting.md) for usage patterns.

::: agenticapi.harness.policy.budget_policy.BudgetPolicy

::: agenticapi.harness.policy.budget_policy.BudgetEvaluationContext

::: agenticapi.harness.policy.budget_policy.CostEstimate

::: agenticapi.harness.policy.budget_policy.SpendStore

::: agenticapi.harness.policy.budget_policy.InMemorySpendStore

## PricingRegistry

Per-1k-token pricing table with a factory that ships the April 2026 public-price snapshot. Accepts overrides for custom or fine-tuned models.

::: agenticapi.harness.policy.pricing.PricingRegistry

::: agenticapi.harness.policy.pricing.ModelPricing
