"""``BudgetPolicy`` — enforce per-request, per-session, and per-user cost ceilings.

This is the cost-governance arm of AgenticAPI's harness. It is a
:class:`Policy` like every other policy, so it composes naturally
with ``CodePolicy`` / ``DataPolicy`` / ``ResourcePolicy`` and is
evaluated by the same :class:`PolicyEvaluator`.

Lifecycle.

Two evaluation passes per request:

1. **Pre-call** — invoked before the LLM is contacted. The policy
   estimates the worst-case cost from the prompt's input-token
   footprint plus the configured ``max_output_tokens`` ceiling, then
   compares against every active budget. Any breach raises
   :class:`BudgetExceeded` which inherits from :class:`PolicyViolation`
   and maps to HTTP 402 (Payment Required).
2. **Post-call** — invoked after the LLM call returns with actual
   ``LLMUsage``. The policy reconciles the running total to actuals
   and updates the per-scope spend store. Subsequent requests in the
   same session/user/endpoint window see the higher number on their
   pre-call check.

Spend store.

By default, running totals live in an in-memory dict keyed by
``(scope_kind, scope_id)`` (e.g. ``("session", "alice-session-1")``).
For multi-host deployments, swap in a Redis-backed
:class:`SpendStore` (not shipped in this iteration — out of scope for
A4; the protocol is in place so it can be added without breaking
changes).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, ClassVar, Protocol, runtime_checkable

import structlog
from pydantic import ConfigDict, Field

from agenticapi.exceptions import BudgetExceeded
from agenticapi.harness.policy.base import Policy, PolicyResult
from agenticapi.harness.policy.pricing import (
    PricingRegistry,  # noqa: TC001 — needed at runtime as a Pydantic field type
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Spend store
# ---------------------------------------------------------------------------


@runtime_checkable
class SpendStore(Protocol):
    """Protocol for the running-spend tracker.

    Implementations may be in-memory, Redis-backed, database-backed,
    or anything else. The protocol is intentionally tiny so that
    high-traffic deployments can swap in a sharded backend without
    touching the policy.
    """

    def get(self, scope: str, key: str, *, day: date | None = None) -> float:
        """Return the running total in USD for the given scope/key/day."""
        ...

    def add(self, scope: str, key: str, amount_usd: float, *, day: date | None = None) -> None:
        """Atomically add ``amount_usd`` to the running total."""
        ...

    def reset(self, scope: str, key: str | None = None) -> None:
        """Forget recorded spend (for testing or manual rollover)."""
        ...


class InMemorySpendStore:
    """Process-local :class:`SpendStore` keyed by scope/key/day.

    Day-scoped totals key off ``(scope, key, isoformat(day))`` so the
    same store cleanly handles per-day budgets without rollover code.
    Other scopes ignore the day component.
    """

    def __init__(self) -> None:
        self._totals: dict[tuple[str, str, str | None], float] = defaultdict(float)

    @staticmethod
    def _key(scope: str, key: str, day: date | None) -> tuple[str, str, str | None]:
        if scope == "user_per_day":
            d = (day or datetime.now(tz=UTC).date()).isoformat()
            return (scope, key, d)
        return (scope, key, None)

    def get(self, scope: str, key: str, *, day: date | None = None) -> float:
        return self._totals.get(self._key(scope, key, day), 0.0)

    def add(self, scope: str, key: str, amount_usd: float, *, day: date | None = None) -> None:
        self._totals[self._key(scope, key, day)] += amount_usd

    def reset(self, scope: str, key: str | None = None) -> None:
        if key is None:
            for k in [k for k in self._totals if k[0] == scope]:
                del self._totals[k]
        else:
            for k in [k for k in self._totals if k[0] == scope and k[1] == key]:
                del self._totals[k]


# ---------------------------------------------------------------------------
# BudgetPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Result of a pre-call cost estimate.

    Attributes:
        model: Model the estimate was made for.
        estimated_input_tokens: Token count fed into the estimate.
        estimated_output_tokens: Worst-case output token count.
        estimated_cost_usd: Computed worst-case cost.
    """

    model: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float


@dataclass(slots=True)
class BudgetEvaluationContext:
    """Per-request context that callers pass into :meth:`BudgetPolicy.estimate_and_enforce`.

    Attributes:
        endpoint_name: Endpoint receiving the call.
        session_id: Optional session identifier.
        user_id: Optional authenticated user identifier.
        model: LLM model identifier.
        input_tokens: Estimated prompt token count.
        max_output_tokens: Cap on output tokens (used for the estimate).
    """

    endpoint_name: str
    session_id: str | None
    user_id: str | None
    model: str
    input_tokens: int
    max_output_tokens: int = 1024


class BudgetPolicy(Policy):
    """Cost-budget enforcement policy.

    Composes with the rest of the harness via :class:`PolicyEvaluator`,
    but its real entry point is :meth:`estimate_and_enforce`, which
    the framework calls *before* the LLM call fires. The standard
    :meth:`Policy.evaluate` hook is also implemented (returning a
    no-op result) so existing harness pipelines that pass code-only
    policies through ``PolicyEvaluator`` continue to compose.

    Example:
        from agenticapi import BudgetPolicy
        from agenticapi.harness.policy.pricing import PricingRegistry

        pricing = PricingRegistry.default()
        budget = BudgetPolicy(
            pricing=pricing,
            max_per_request_usd=0.50,
            max_per_session_usd=5.00,
            max_per_user_per_day_usd=50.00,
        )
        harness = HarnessEngine(policies=[budget, ...])
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    pricing: PricingRegistry
    max_per_request_usd: float | None = None
    max_per_session_usd: float | None = None
    max_per_user_per_day_usd: float | None = None
    max_per_endpoint_per_day_usd: float | None = None
    spend_store: SpendStore = Field(default_factory=InMemorySpendStore)

    # ------------------------------------------------------------------
    # Policy contract
    # ------------------------------------------------------------------

    def evaluate(
        self,
        *,
        code: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """No-op for code-level evaluation.

        BudgetPolicy operates on the LLM-call boundary via
        :meth:`estimate_and_enforce` and :meth:`record_actual`,
        not on the generated code itself. This stub keeps it
        composable with the existing :class:`PolicyEvaluator`.
        """
        del code, intent_action, intent_domain, kwargs
        return PolicyResult(allowed=True, policy_name="BudgetPolicy")

    # ------------------------------------------------------------------
    # Pre-call estimate + enforcement
    # ------------------------------------------------------------------

    def estimate_and_enforce(self, ctx: BudgetEvaluationContext) -> CostEstimate:
        """Estimate cost for the upcoming LLM call and enforce all budgets.

        Args:
            ctx: Per-request context with the active session/user/endpoint
                and the model + token estimates.

        Returns:
            The :class:`CostEstimate` that was computed.

        Raises:
            BudgetExceeded: If any configured budget would be breached.
        """
        cost = self.pricing.estimate_cost(
            model=ctx.model,
            input_tokens=ctx.input_tokens,
            output_tokens=ctx.max_output_tokens,
        )
        estimate = CostEstimate(
            model=ctx.model,
            estimated_input_tokens=ctx.input_tokens,
            estimated_output_tokens=ctx.max_output_tokens,
            estimated_cost_usd=cost,
        )

        # Per-request ceiling.
        if self.max_per_request_usd is not None and cost > self.max_per_request_usd:
            raise BudgetExceeded(
                scope="request",
                limit_usd=self.max_per_request_usd,
                observed_usd=cost,
                model=ctx.model,
            )

        # Per-session running total + ceiling.
        if self.max_per_session_usd is not None and ctx.session_id:
            current = self.spend_store.get("session", ctx.session_id)
            projected = current + cost
            if projected > self.max_per_session_usd:
                raise BudgetExceeded(
                    scope="session",
                    limit_usd=self.max_per_session_usd,
                    observed_usd=projected,
                    model=ctx.model,
                )

        # Per-user-per-day running total + ceiling.
        if self.max_per_user_per_day_usd is not None and ctx.user_id:
            today = datetime.now(tz=UTC).date()
            current = self.spend_store.get("user_per_day", ctx.user_id, day=today)
            projected = current + cost
            if projected > self.max_per_user_per_day_usd:
                raise BudgetExceeded(
                    scope="user_per_day",
                    limit_usd=self.max_per_user_per_day_usd,
                    observed_usd=projected,
                    model=ctx.model,
                )

        # Per-endpoint-per-day total.
        if self.max_per_endpoint_per_day_usd is not None and ctx.endpoint_name:
            today = datetime.now(tz=UTC).date()
            current = self.spend_store.get("endpoint_per_day", ctx.endpoint_name, day=today)
            projected = current + cost
            if projected > self.max_per_endpoint_per_day_usd:
                raise BudgetExceeded(
                    scope="endpoint_per_day",
                    limit_usd=self.max_per_endpoint_per_day_usd,
                    observed_usd=projected,
                    model=ctx.model,
                )

        return estimate

    # ------------------------------------------------------------------
    # Post-call reconciliation
    # ------------------------------------------------------------------

    def record_actual(
        self,
        ctx: BudgetEvaluationContext,
        *,
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> float:
        """Record the actual spend after the LLM call returns.

        The pre-call estimate uses the worst-case ``max_output_tokens``;
        the post-call reconciliation replaces that estimate with the
        actual usage so the running totals reflect what really happened.

        Args:
            ctx: The same context used for the pre-call estimate.
            actual_input_tokens: Real input tokens reported by the LLM.
            actual_output_tokens: Real output tokens reported by the LLM.

        Returns:
            The actual cost in USD that was added to the running totals.
        """
        actual_cost = self.pricing.estimate_cost(
            model=ctx.model,
            input_tokens=actual_input_tokens,
            output_tokens=actual_output_tokens,
        )
        if ctx.session_id and self.max_per_session_usd is not None:
            self.spend_store.add("session", ctx.session_id, actual_cost)
        if ctx.user_id and self.max_per_user_per_day_usd is not None:
            today = datetime.now(tz=UTC).date()
            self.spend_store.add("user_per_day", ctx.user_id, actual_cost, day=today)
        if ctx.endpoint_name and self.max_per_endpoint_per_day_usd is not None:
            today = datetime.now(tz=UTC).date()
            self.spend_store.add("endpoint_per_day", ctx.endpoint_name, actual_cost, day=today)
        return actual_cost

    # ------------------------------------------------------------------
    # Inspection helpers (handy for /metrics integrations later)
    # ------------------------------------------------------------------

    def current_spend(self, *, scope: str, key: str, day: date | None = None) -> float:
        """Return the running spend in USD for a given scope/key."""
        return self.spend_store.get(scope, key, day=day)


__all__ = [
    "BudgetEvaluationContext",
    "BudgetPolicy",
    "CostEstimate",
    "InMemorySpendStore",
    "SpendStore",
]
