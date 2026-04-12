"""Approved-Code Cache example: skip the LLM when the answer is cached.

Demonstrates AgenticAPI's **approved-code cache** (Phase C5) — the
cost-saving primitive that skips the code-generation LLM call when an
identical intent shape has already been generated, approved, and
shipped. Cached code still runs through every downstream layer
(policies, static analysis, sandbox, monitors, validators, audit), so
the cache is strictly an LLM-call optimisation, never a safety
downgrade.

This is the pattern that turns a $0.05 / 800 ms code-gen call into a
$0.00 / < 1 ms cache hit for the 80%+ of production requests that
repeat the same intent shape with different parameters.

Features demonstrated
---------------------

- ``AgenticApp(code_cache=InMemoryCodeCache(...))`` — framework-level
  wiring so the harness path checks the cache before calling the LLM.
- ``InMemoryCodeCache(max_entries=..., ttl_seconds=...)`` — bounded
  LRU cache with configurable entry limit and time-to-live.
- ``make_cache_key(...)`` — deterministic SHA-256 key from endpoint,
  intent classification, tool set, and policy set.
- ``CachedCode`` — frozen dataclass with ``hits`` counter for
  diagnostics.
- Cache inspection endpoints — show cache size, top entries by hit
  count, and per-key lookup.
- Cache management — clear the cache on demand (simulating a rollout).
- The cache key includes sorted tool names and policy class names so
  adding/removing a tool or policy **automatically invalidates** stale
  entries.

No LLM or API key required. The example uses direct handlers that
simulate the "pre-cached" scenario by writing entries to the cache
programmatically, then demonstrates hits and misses.

Run
---

::

    uvicorn examples.24_code_cache.app:app --reload
    # or
    agenticapi dev --app examples.24_code_cache.app:app

Walkthrough with curl
---------------------

::

    # 1. Check initial cache state (empty)
    curl -s -X POST http://127.0.0.1:8000/agent/cache.stats \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show cache stats"}' | python3 -m json.tool

    # 2. Seed the cache with a pre-approved code block
    curl -s -X POST http://127.0.0.1:8000/agent/cache.seed \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Seed cache for order queries"}' | python3 -m json.tool

    # 3. Look up the cache — should be a HIT
    curl -s -X POST http://127.0.0.1:8000/agent/cache.lookup \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Look up order query cache entry"}' | python3 -m json.tool

    # 4. Look up with different parameters — should be a MISS
    curl -s -X POST http://127.0.0.1:8000/agent/cache.lookup_different \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Look up product query"}' | python3 -m json.tool

    # 5. Seed again and hit again — hit counter increments
    curl -s -X POST http://127.0.0.1:8000/agent/cache.lookup \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Look up order query cache entry again"}' | python3 -m json.tool

    # 6. Inspect the top entries (most hits)
    curl -s -X POST http://127.0.0.1:8000/agent/cache.stats \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show cache stats now"}' | python3 -m json.tool

    # 7. Clear the cache (simulates a deployment rollout)
    curl -s -X POST http://127.0.0.1:8000/agent/cache.clear \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Clear cache"}' | python3 -m json.tool

    # 8. Verify cache is empty after clear
    curl -s -X POST http://127.0.0.1:8000/agent/cache.stats \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show stats after clear"}' | python3 -m json.tool

    # 9. Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from agenticapi import AgenticApp
from agenticapi.runtime.code_cache import (
    CachedCode,
    InMemoryCodeCache,
    make_cache_key,
)

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# 1. Response models
# ---------------------------------------------------------------------------


class CacheStatsResponse(BaseModel):
    """Current state of the cache."""

    size: int
    max_entries: int
    ttl_seconds: float | None
    top_entries: list[dict[str, Any]]


class SeedResponse(BaseModel):
    """Result of seeding a cache entry."""

    key: str
    code_preview: str
    message: str


class LookupResponse(BaseModel):
    """Result of a cache lookup."""

    key: str
    hit: bool
    code: str | None
    hits: int
    reasoning: str | None
    message: str


class ClearResponse(BaseModel):
    """Result of clearing the cache."""

    cleared: bool
    message: str


# ---------------------------------------------------------------------------
# 2. The cache instance + app wiring
# ---------------------------------------------------------------------------
#
# In production, ``code_cache=`` on ``AgenticApp`` integrates the cache
# into the harness path — ``_execute_with_harness`` checks it before
# calling the LLM. This example uses direct handlers that demonstrate
# the cache primitives programmatically so no LLM is needed.

cache = InMemoryCodeCache(max_entries=100, ttl_seconds=3600)

app = AgenticApp(
    title="Approved-Code Cache Demo",
    version="1.0.0",
    description=(
        "Demonstrates the approved-code cache (C5) — the LLM-call "
        "optimisation that skips code generation on cache hits. "
        "No LLM required."
    ),
    code_cache=cache,
)


# ---------------------------------------------------------------------------
# 3. Simulated cache key inputs
# ---------------------------------------------------------------------------
#
# In production, the harness builds these from the live request. Here
# we define two fixed "intent shapes" so the demo is deterministic.

ORDER_QUERY_INPUTS = {
    "endpoint_name": "orders.query",
    "intent_action": "query",
    "intent_domain": "orders",
    "tool_names": ["database", "cache"],
    "policy_names": ["CodePolicy", "DataPolicy"],
    "intent_parameters": {"time_range": "last_week", "status": "open"},
}

PRODUCT_QUERY_INPUTS = {
    "endpoint_name": "products.search",
    "intent_action": "search",
    "intent_domain": "products",
    "tool_names": ["database"],
    "policy_names": ["CodePolicy"],
    "intent_parameters": {"category": "electronics"},
}

# Pre-compute the keys so handlers can demonstrate hits vs misses.
ORDER_KEY = make_cache_key(**ORDER_QUERY_INPUTS)
PRODUCT_KEY = make_cache_key(**PRODUCT_QUERY_INPUTS)

# A simulated "approved" code block — what the LLM would have generated.
APPROVED_ORDER_CODE = """\
# Generated and approved by the harness on a previous request.
# This code would normally be produced by CodeGenerator → PolicyEvaluator
# → StaticAnalysis → ApprovalCheck → ProcessSandbox.
result = await db.execute("SELECT * FROM orders WHERE status = 'open' AND created_at > now() - interval '7 days'")
return {"orders": result.rows, "count": len(result.rows)}
"""


# ---------------------------------------------------------------------------
# 4. Endpoints
# ---------------------------------------------------------------------------


@app.agent_endpoint(
    name="cache.seed",
    description="Seed the cache with a pre-approved code block.",
    response_model=SeedResponse,
)
async def seed_cache(intent: Intent, context: AgentContext) -> SeedResponse:
    """Write a ``CachedCode`` entry into the cache.

    In production, the harness writes to the cache after a successful
    code-generation + policy-approval cycle. This endpoint simulates
    that by writing a fixed entry so the lookup endpoint can
    demonstrate a cache hit.
    """
    entry = CachedCode(
        key=ORDER_KEY,
        code=APPROVED_ORDER_CODE,
        reasoning="Generated SQL query for open orders in the last week",
        confidence=0.95,
        created_at=datetime.now(tz=UTC),
    )
    cache.put(entry)
    return SeedResponse(
        key=ORDER_KEY[:16] + "...",
        code_preview=APPROVED_ORDER_CODE.strip().split("\n")[-1][:80],
        message="Cached one approved code block for the order-query intent shape.",
    )


@app.agent_endpoint(
    name="cache.lookup",
    description="Look up the order-query cache entry (should be a HIT after seeding).",
    response_model=LookupResponse,
)
async def lookup_order(intent: Intent, context: AgentContext) -> LookupResponse:
    """Demonstrate a cache **hit**.

    This uses the same ``make_cache_key`` inputs as the seed endpoint,
    so the key matches. The ``hits`` counter on the entry increments
    on every successful lookup — useful for diagnosing which intent
    shapes are the most common (and therefore the biggest cost savers).
    """
    entry = cache.get(ORDER_KEY)
    if entry is not None:
        return LookupResponse(
            key=ORDER_KEY[:16] + "...",
            hit=True,
            code=entry.code,
            hits=entry.hits,
            reasoning=entry.reasoning,
            message=f"Cache HIT. This entry has been served {entry.hits} time(s). The LLM call was skipped.",
        )
    return LookupResponse(
        key=ORDER_KEY[:16] + "...",
        hit=False,
        code=None,
        hits=0,
        reasoning=None,
        message="Cache MISS. The LLM would be called to generate code.",
    )


@app.agent_endpoint(
    name="cache.lookup_different",
    description="Look up a different intent shape (should be a MISS).",
    response_model=LookupResponse,
)
async def lookup_product(intent: Intent, context: AgentContext) -> LookupResponse:
    """Demonstrate a cache **miss**.

    This uses the ``PRODUCT_QUERY_INPUTS`` key, which was never seeded.
    Different endpoint, different domain, different tool set — the
    SHA-256 key is completely different from the order-query entry.
    """
    entry = cache.get(PRODUCT_KEY)
    if entry is not None:
        return LookupResponse(
            key=PRODUCT_KEY[:16] + "...",
            hit=True,
            code=entry.code,
            hits=entry.hits,
            reasoning=entry.reasoning,
            message=f"Cache HIT ({entry.hits} hits).",
        )
    return LookupResponse(
        key=PRODUCT_KEY[:16] + "...",
        hit=False,
        code=None,
        hits=0,
        reasoning=None,
        message="Cache MISS — this intent shape has never been cached.",
    )


@app.agent_endpoint(
    name="cache.stats",
    description="Inspect the cache: size, TTL, top entries by hit count.",
    response_model=CacheStatsResponse,
)
async def cache_stats(intent: Intent, context: AgentContext) -> CacheStatsResponse:
    """Return diagnostics about the cache.

    The ``top_entries`` field shows the most-hit entries, which tells
    operators which intent shapes are the biggest cost savers. In
    production, wire this into a Grafana panel via the
    ``agenticapi_code_cache_hits_total`` OTEL metric.
    """
    top = cache.top_entries(limit=5)
    return CacheStatsResponse(
        size=len(cache),
        max_entries=cache._max_entries,
        ttl_seconds=cache._ttl_seconds,
        top_entries=[
            {
                "key": e.key[:16] + "...",
                "hits": e.hits,
                "confidence": e.confidence,
                "code_preview": e.code.strip().split("\n")[-1][:60],
                "age_seconds": round((datetime.now(tz=UTC) - e.created_at).total_seconds(), 1),
            }
            for e in top
        ],
    )


@app.agent_endpoint(
    name="cache.clear",
    description="Clear the entire cache (simulates a deployment rollout).",
    response_model=ClearResponse,
)
async def clear_cache(intent: Intent, context: AgentContext) -> ClearResponse:
    """Wipe every cached entry.

    Call this when deploying new code, changing policies, or swapping
    LLM models — any change that could make cached code stale. In
    production, wire this into your CI/CD pipeline's post-deploy hook.
    """
    cache.clear()
    return ClearResponse(
        cleared=True,
        message="Cache cleared. All entries evicted. Next requests will call the LLM.",
    )


# ---------------------------------------------------------------------------
# 5. Exports
# ---------------------------------------------------------------------------

__all__ = ["app", "cache"]
