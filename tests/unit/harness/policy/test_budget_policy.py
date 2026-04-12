"""Unit tests for ``BudgetPolicy`` and ``PricingRegistry``.

Covers pricing lookup, cost estimation, per-request / per-session /
per-user-per-day enforcement, post-call reconciliation, and
backward-compatible composition with the existing ``PolicyEvaluator``.
"""

from __future__ import annotations

import pytest

from agenticapi import BudgetExceeded, BudgetPolicy, PricingRegistry
from agenticapi.harness.policy.budget_policy import (
    BudgetEvaluationContext,
    InMemorySpendStore,
)
from agenticapi.harness.policy.pricing import ModelPricing


class TestPricingRegistry:
    def test_default_includes_anthropic_openai_gemini(self) -> None:
        reg = PricingRegistry.default()
        # At minimum: one model from each provider plus the mock.
        models = reg.known_models()
        assert any(m.startswith("claude-") for m in models)
        assert any(m.startswith("gpt-") or m.startswith("gpt-4") for m in models)
        assert any(m.startswith("gemini-") for m in models)
        assert "mock" in reg

    def test_estimate_cost_basic(self) -> None:
        reg = PricingRegistry()
        reg.set("test-model", input_usd_per_1k=2.0, output_usd_per_1k=10.0)
        cost = reg.estimate_cost(
            model="test-model",
            input_tokens=1000,
            output_tokens=500,
        )
        # 1000 * 2 / 1000 + 500 * 10 / 1000 == 2 + 5 == 7
        assert cost == pytest.approx(7.0)

    def test_estimate_cost_unknown_model_returns_zero(self) -> None:
        """Unknown models cost 0 (with a logged warning) — graceful degrade."""
        reg = PricingRegistry()
        cost = reg.estimate_cost(model="not-a-real-model", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_set_and_get_roundtrip(self) -> None:
        reg = PricingRegistry()
        reg.set("custom", input_usd_per_1k=1.5, output_usd_per_1k=4.5)
        pricing = reg.get("custom")
        assert pricing == ModelPricing(input_usd_per_1k=1.5, output_usd_per_1k=4.5)

    def test_cache_read_and_write_pricing(self) -> None:
        reg = PricingRegistry()
        reg.set(
            "cached-model",
            input_usd_per_1k=2.0,
            output_usd_per_1k=10.0,
            cache_read_usd_per_1k=0.5,
            cache_write_usd_per_1k=2.5,
        )
        cost = reg.estimate_cost(
            model="cached-model",
            input_tokens=1000,
            output_tokens=0,
            cache_read_tokens=2000,
            cache_write_tokens=1000,
        )
        # 1000*2/1000 + 0 + 2000*0.5/1000 + 1000*2.5/1000 = 2 + 1 + 2.5 = 5.5
        assert cost == pytest.approx(5.5)

    def test_known_models_sorted(self) -> None:
        reg = PricingRegistry()
        reg.set("zebra", input_usd_per_1k=1, output_usd_per_1k=1)
        reg.set("apple", input_usd_per_1k=1, output_usd_per_1k=1)
        assert reg.known_models() == ["apple", "zebra"]


class TestBudgetPolicyEnforcement:
    def _budget(self, **kwargs: object) -> BudgetPolicy:
        pricing = PricingRegistry()
        pricing.set("test", input_usd_per_1k=10.0, output_usd_per_1k=10.0)
        return BudgetPolicy(pricing=pricing, **kwargs)  # type: ignore[arg-type]

    def test_per_request_ceiling_blocks(self) -> None:
        policy = self._budget(max_per_request_usd=0.01)
        ctx = BudgetEvaluationContext(
            endpoint_name="ep",
            session_id=None,
            user_id=None,
            model="test",
            input_tokens=1000,  # 1000 * 10 / 1000 = $10 input alone
            max_output_tokens=10,
        )
        with pytest.raises(BudgetExceeded) as exc_info:
            policy.estimate_and_enforce(ctx)
        assert exc_info.value.scope == "request"

    def test_per_request_ceiling_allows(self) -> None:
        policy = self._budget(max_per_request_usd=1.0)
        ctx = BudgetEvaluationContext(
            endpoint_name="ep",
            session_id=None,
            user_id=None,
            model="test",
            input_tokens=10,  # 10 * 10 / 1000 = $0.10
            max_output_tokens=10,
        )
        estimate = policy.estimate_and_enforce(ctx)
        assert estimate.estimated_cost_usd == pytest.approx(0.20)

    def test_per_session_running_total(self) -> None:
        """Repeated calls in the same session accumulate spend."""
        policy = self._budget(max_per_session_usd=1.0)
        ctx = BudgetEvaluationContext(
            endpoint_name="ep",
            session_id="sess1",
            user_id=None,
            model="test",
            input_tokens=20,  # $0.20 input
            max_output_tokens=20,  # $0.20 output → $0.40 total
        )
        # First call OK.
        policy.estimate_and_enforce(ctx)
        policy.record_actual(ctx, actual_input_tokens=20, actual_output_tokens=20)

        # Second OK ($0.40 + $0.40 = $0.80 < $1.00).
        policy.estimate_and_enforce(ctx)
        policy.record_actual(ctx, actual_input_tokens=20, actual_output_tokens=20)

        # Third would push us over the cap.
        with pytest.raises(BudgetExceeded) as exc_info:
            policy.estimate_and_enforce(ctx)
        assert exc_info.value.scope == "session"

    def test_per_user_per_day(self) -> None:
        policy = self._budget(max_per_user_per_day_usd=0.50)
        ctx = BudgetEvaluationContext(
            endpoint_name="ep",
            session_id=None,
            user_id="alice",
            model="test",
            input_tokens=10,
            max_output_tokens=10,
        )
        # First call $0.20 — OK.
        policy.estimate_and_enforce(ctx)
        policy.record_actual(ctx, actual_input_tokens=10, actual_output_tokens=10)
        # Second call would push to $0.40 — still OK.
        policy.estimate_and_enforce(ctx)
        policy.record_actual(ctx, actual_input_tokens=10, actual_output_tokens=10)
        # Third call would push to $0.60 — exceeds.
        with pytest.raises(BudgetExceeded) as exc_info:
            policy.estimate_and_enforce(ctx)
        assert exc_info.value.scope == "user_per_day"

    def test_no_budgets_set_means_no_enforcement(self) -> None:
        policy = self._budget()
        ctx = BudgetEvaluationContext(
            endpoint_name="ep",
            session_id="sess",
            user_id="alice",
            model="test",
            input_tokens=10_000_000,
            max_output_tokens=10_000_000,
        )
        # No raises — gigantic estimate, no caps.
        estimate = policy.estimate_and_enforce(ctx)
        assert estimate.estimated_cost_usd > 0

    def test_record_actual_updates_running_total(self) -> None:
        policy = self._budget(max_per_session_usd=1.0)
        ctx = BudgetEvaluationContext(
            endpoint_name="ep",
            session_id="sess1",
            user_id=None,
            model="test",
            input_tokens=10,
            max_output_tokens=10,
        )
        policy.estimate_and_enforce(ctx)
        actual_cost = policy.record_actual(ctx, actual_input_tokens=10, actual_output_tokens=10)
        assert actual_cost == pytest.approx(0.20)
        assert policy.current_spend(scope="session", key="sess1") == pytest.approx(0.20)

    def test_budget_exceeded_carries_metadata(self) -> None:
        policy = self._budget(max_per_request_usd=0.01)
        ctx = BudgetEvaluationContext(
            endpoint_name="ep",
            session_id=None,
            user_id=None,
            model="test",
            input_tokens=1000,
            max_output_tokens=10,
        )
        with pytest.raises(BudgetExceeded) as exc_info:
            policy.estimate_and_enforce(ctx)
        err = exc_info.value
        assert err.limit_usd == 0.01
        assert err.observed_usd > 0.01
        assert err.model == "test"
        assert err.scope == "request"

    def test_budget_exceeded_is_policy_violation(self) -> None:
        """BudgetExceeded must be catchable as PolicyViolation for back-compat."""
        from agenticapi.exceptions import PolicyViolation

        policy = self._budget(max_per_request_usd=0.01)
        ctx = BudgetEvaluationContext(
            endpoint_name="ep",
            session_id=None,
            user_id=None,
            model="test",
            input_tokens=1000,
            max_output_tokens=10,
        )
        with pytest.raises(PolicyViolation):
            policy.estimate_and_enforce(ctx)


class TestBudgetPolicyComposability:
    def test_evaluate_method_is_noop(self) -> None:
        """The Policy.evaluate hook is a no-op so it composes with the evaluator."""
        policy = BudgetPolicy(
            pricing=PricingRegistry.default(),
            max_per_request_usd=1.0,
        )
        result = policy.evaluate(code="result = 1+1", intent_action="read", intent_domain="test")
        assert result.allowed is True

    def test_in_memory_spend_store_resets(self) -> None:
        store = InMemorySpendStore()
        store.add("session", "s1", 1.50)
        assert store.get("session", "s1") == pytest.approx(1.50)
        store.reset("session", "s1")
        assert store.get("session", "s1") == 0.0

    def test_in_memory_spend_store_resets_all_for_scope(self) -> None:
        store = InMemorySpendStore()
        store.add("session", "s1", 1.0)
        store.add("session", "s2", 2.0)
        store.reset("session")
        assert store.get("session", "s1") == 0.0
        assert store.get("session", "s2") == 0.0
