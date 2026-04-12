"""LLM pricing registry for cost estimation and budget enforcement.

The :class:`PricingRegistry` maps a model identifier to per-token
prices in USD. It is consumed by :class:`BudgetPolicy` to estimate
request cost from a token count and to enforce ceilings before the
LLM call fires.

Prices are stored as USD per **1 000 tokens** (the convention used by
every major LLM provider's published price sheet) and converted to
absolute USD by the registry on lookup.

The default registry ships with a snapshot of public list prices for
the families AgenticAPI supports out of the box. Users override or
extend it via :meth:`PricingRegistry.set` for custom models, contract
discounts, or fine-tuned variants.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Per-1k-token pricing for a single LLM model.

    Attributes:
        input_usd_per_1k: Cost per 1 000 prompt (input) tokens.
        output_usd_per_1k: Cost per 1 000 completion (output) tokens.
        cache_read_usd_per_1k: Optional cost per 1 000 cache-read
            tokens. When None, treated as equal to input_usd_per_1k.
        cache_write_usd_per_1k: Optional cost per 1 000 cache-write
            tokens. When None, treated as equal to input_usd_per_1k.
    """

    input_usd_per_1k: float
    output_usd_per_1k: float
    cache_read_usd_per_1k: float | None = None
    cache_write_usd_per_1k: float | None = None


# Snapshot of public list prices as of 2026-04. Users should override
# these via PricingRegistry.set() for production deployments to reflect
# their actual contract pricing.
_DEFAULT_PRICES: dict[str, ModelPricing] = {
    # --- Anthropic ---
    "claude-opus-4-6": ModelPricing(input_usd_per_1k=15.00, output_usd_per_1k=75.00),
    "claude-sonnet-4-6": ModelPricing(input_usd_per_1k=3.00, output_usd_per_1k=15.00),
    "claude-haiku-4-5": ModelPricing(input_usd_per_1k=1.00, output_usd_per_1k=5.00),
    "claude-haiku-4-5-20251001": ModelPricing(input_usd_per_1k=1.00, output_usd_per_1k=5.00),
    # --- OpenAI ---
    "gpt-5.4": ModelPricing(input_usd_per_1k=10.00, output_usd_per_1k=30.00),
    "gpt-5.4-mini": ModelPricing(input_usd_per_1k=0.50, output_usd_per_1k=1.50),
    "gpt-4o": ModelPricing(input_usd_per_1k=2.50, output_usd_per_1k=10.00),
    "gpt-4o-mini": ModelPricing(input_usd_per_1k=0.15, output_usd_per_1k=0.60),
    # --- Google Gemini ---
    "gemini-2.5-pro": ModelPricing(input_usd_per_1k=1.25, output_usd_per_1k=10.00),
    "gemini-2.5-flash": ModelPricing(input_usd_per_1k=0.075, output_usd_per_1k=0.30),
    # --- Mock backend (zero cost — useful in tests) ---
    "mock": ModelPricing(input_usd_per_1k=0.0, output_usd_per_1k=0.0),
}


class PricingRegistry:
    """Mutable registry of model → pricing.

    Example:
        pricing = PricingRegistry.default()
        # Override with negotiated contract pricing:
        pricing.set("claude-sonnet-4-6", input_usd_per_1k=2.40, output_usd_per_1k=12.00)
        cost = pricing.estimate_cost(
            model="claude-sonnet-4-6",
            input_tokens=1500,
            output_tokens=400,
        )
        # cost == (1500 * 2.40 + 400 * 12.00) / 1000 == $8.40
    """

    def __init__(self, prices: dict[str, ModelPricing] | None = None) -> None:
        """Initialize the registry.

        Args:
            prices: Optional initial pricing map. If omitted, the
                registry starts empty (use :meth:`default` for the
                shipped snapshot).
        """
        self._prices: dict[str, ModelPricing] = dict(prices or {})

    @classmethod
    def default(cls) -> PricingRegistry:
        """Return a registry pre-populated with the shipped price snapshot."""
        return cls(prices=dict(_DEFAULT_PRICES))

    def set(
        self,
        model: str,
        *,
        input_usd_per_1k: float,
        output_usd_per_1k: float,
        cache_read_usd_per_1k: float | None = None,
        cache_write_usd_per_1k: float | None = None,
    ) -> None:
        """Register or override pricing for a single model.

        Args:
            model: Model identifier as reported by the LLM backend.
            input_usd_per_1k: USD per 1 000 input tokens.
            output_usd_per_1k: USD per 1 000 output tokens.
            cache_read_usd_per_1k: Optional cache-read price.
            cache_write_usd_per_1k: Optional cache-write price.
        """
        self._prices[model] = ModelPricing(
            input_usd_per_1k=input_usd_per_1k,
            output_usd_per_1k=output_usd_per_1k,
            cache_read_usd_per_1k=cache_read_usd_per_1k,
            cache_write_usd_per_1k=cache_write_usd_per_1k,
        )

    def get(self, model: str) -> ModelPricing | None:
        """Return the pricing entry for ``model`` if known, else ``None``."""
        return self._prices.get(model)

    def estimate_cost(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Estimate USD cost for a single LLM call.

        Unknown models cost 0.0 (with a warning) so the framework
        degrades gracefully on a fresh model rather than raising — a
        production deployment can opt into strict mode by checking
        ``get(model) is None`` first.

        Args:
            model: Model identifier.
            input_tokens: Number of prompt tokens.
            output_tokens: Number of completion tokens.
            cache_read_tokens: Optional cache-read token count.
            cache_write_tokens: Optional cache-write token count.

        Returns:
            Estimated cost in USD.
        """
        pricing = self._prices.get(model)
        if pricing is None:
            logger.warning("pricing_unknown_model", model=model)
            return 0.0

        cost = (input_tokens * pricing.input_usd_per_1k) / 1000.0
        cost += (output_tokens * pricing.output_usd_per_1k) / 1000.0
        if cache_read_tokens:
            rate = pricing.cache_read_usd_per_1k or pricing.input_usd_per_1k
            cost += (cache_read_tokens * rate) / 1000.0
        if cache_write_tokens:
            rate = pricing.cache_write_usd_per_1k or pricing.input_usd_per_1k
            cost += (cache_write_tokens * rate) / 1000.0
        return cost

    def known_models(self) -> list[str]:
        """Return a sorted list of model identifiers known to this registry."""
        return sorted(self._prices.keys())

    def __contains__(self, model: str) -> bool:
        return model in self._prices

    def __len__(self) -> int:
        return len(self._prices)


__all__ = ["ModelPricing", "PricingRegistry"]
