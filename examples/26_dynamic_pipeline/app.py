"""Dynamic pipeline example: middleware-like stage composition for agent requests.

Demonstrates ``DynamicPipeline`` — AgenticAPI's mechanism for composing
pre-handler processing stages that run before the endpoint handler
executes. Think of it as **middleware that the handler can inspect and
that carries data forward in a shared context dict**, without wrapping
the entire ASGI app.

Where Starlette middleware wraps the whole application and has no
visibility into the handler's intent, ``DynamicPipeline`` stages:

* Run **inside** the agent request lifecycle, after auth and intent
  parsing but before the handler.
* Receive and return a **mutable context dict** that the handler can
  read — so a rate-limit stage can set ``ctx["rate_limited"] = True``
  and the handler can branch on it.
* Are split into **base stages** (always run, in order) and
  **available stages** (selected per-request by the caller or by the
  handler's business logic).
* Are **timed** — ``PipelineResult.stage_timings_ms`` gives per-stage
  latency for free, useful for observability.

The app models an order API with four stages:

1. **request_id** (base, always) — stamps every request with a UUID.
2. **rate_limiter** (base, always) — tracks per-session call count and
   sets a ``rate_limited`` flag when the threshold is exceeded.
3. **geo_enrichment** (available, opt-in) — looks up the user's region
   from a simulated geo-IP service and tags the context.
4. **discount_calculator** (available, opt-in) — applies a regional
   discount percentage to the context for the handler to use.

Two endpoints exercise the pipeline:

* ``POST /agent/order.place`` — runs all base stages plus optionally
  ``geo_enrichment`` + ``discount_calculator`` (selected by the handler
  based on whether the intent mentions a region). Returns the order
  with the pipeline trace so you can see exactly which stages ran and
  how long each took.
* ``POST /agent/pipeline.info`` — reports the pipeline configuration:
  which stages exist, which are base, which are available.

No LLM or API key required.

Run with::

    uvicorn examples.26_dynamic_pipeline.app:app --reload

Or using the CLI::

    agenticapi dev --app examples.26_dynamic_pipeline.app:app

Walkthrough::

    # 1. Place an order (base stages only — no region mentioned)
    curl -s -X POST http://127.0.0.1:8000/agent/order.place \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Place an order for 3 widgets", "session_id": "alice"}' | python3 -m json.tool

    # 2. Place an order with region — triggers geo + discount stages
    curl -s -X POST http://127.0.0.1:8000/agent/order.place \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Place an order for 5 gadgets in Europe", "session_id": "bob"}' | python3 -m json.tool

    # 3. Repeat a session to trigger the rate limiter (threshold=5)
    for i in 1 2 3 4 5 6; do
        curl -s -X POST http://127.0.0.1:8000/agent/order.place \\
            -H "Content-Type: application/json" \\
            -d '{"intent": "Order 1 item", "session_id": "charlie"}'
        echo
    done
    # -> First 5 succeed, 6th has rate_limited=true

    # 4. Inspect pipeline configuration
    curl -s -X POST http://127.0.0.1:8000/agent/pipeline.info \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "show pipeline"}' | python3 -m json.tool
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agenticapi import AgenticApp, Intent
from agenticapi.application.pipeline import DynamicPipeline, PipelineStage

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# 1. Pipeline stages
# ---------------------------------------------------------------------------
# Each stage is a plain function: dict[str, Any] -> dict[str, Any].
# Both sync and async functions work — the pipeline awaits if needed.


def request_id_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Stamp every request with a unique ID (base stage, always runs)."""
    ctx["request_id"] = str(uuid.uuid4())[:8]
    return ctx


# Simple in-memory session counter for the rate limiter demo.
_session_counts: dict[str, int] = defaultdict(int)
_RATE_LIMIT = 5


def rate_limiter_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Track per-session request count (base stage, always runs).

    Sets ``rate_limited=True`` when the session exceeds the threshold.
    A real implementation would use Redis or a distributed counter.
    """
    session_id = ctx.get("session_id", "anonymous")
    _session_counts[session_id] += 1
    ctx["request_count"] = _session_counts[session_id]
    ctx["rate_limited"] = _session_counts[session_id] > _RATE_LIMIT
    return ctx


# Simulated geo lookup.
_REGIONS = {"europe": "EU", "asia": "APAC", "us": "NA", "america": "NA"}


def geo_enrichment_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Look up the user's region from intent text (available stage, opt-in).

    In a real app this might call a geo-IP service or read from a user
    profile. Here we extract it from the intent keywords.
    """
    intent_text: str = ctx.get("intent_text", "").lower()
    for keyword, region in _REGIONS.items():
        if keyword in intent_text:
            ctx["region"] = region
            break
    else:
        ctx["region"] = "GLOBAL"
    return ctx


# Regional discount table.
_DISCOUNTS = {"EU": 0.10, "APAC": 0.15, "NA": 0.05, "GLOBAL": 0.0}


def discount_calculator_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Calculate a regional discount (available stage, opt-in).

    Uses the ``region`` tag set by ``geo_enrichment_stage``. If geo
    hasn't run, defaults to no discount.
    """
    region = ctx.get("region", "GLOBAL")
    ctx["discount_pct"] = _DISCOUNTS.get(region, 0.0)
    return ctx


# ---------------------------------------------------------------------------
# 2. Pipeline assembly
# ---------------------------------------------------------------------------
# Base stages always run. Available stages are selected per-request.

pipeline = DynamicPipeline(
    base_stages=[
        PipelineStage(
            "request_id",
            description="Stamp every request with a UUID",
            handler=request_id_stage,
            required=True,
            order=10,
        ),
        PipelineStage(
            "rate_limiter",
            description="Per-session rate limiting",
            handler=rate_limiter_stage,
            required=True,
            order=20,
        ),
    ],
    available_stages=[
        PipelineStage(
            "geo_enrichment",
            description="Tag the request with a geographic region",
            handler=geo_enrichment_stage,
            order=30,
        ),
        PipelineStage(
            "discount_calculator",
            description="Apply regional discount percentage",
            handler=discount_calculator_stage,
            order=40,
        ),
    ],
    max_stages=8,
)


# ---------------------------------------------------------------------------
# 3. Response models
# ---------------------------------------------------------------------------


class OrderResponse(BaseModel):
    order_id: str
    item: str
    quantity: int = Field(ge=1)
    discount_pct: float = 0.0
    region: str = "GLOBAL"
    rate_limited: bool = False
    request_count: int = 0
    stages_executed: list[str]
    stage_timings_ms: dict[str, float]


class PipelineInfoResponse(BaseModel):
    base_stages: list[str]
    available_stages: list[str]
    max_stages: int


# ---------------------------------------------------------------------------
# 4. App + endpoints
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Dynamic Pipeline Demo",
    version="1.0.0",
    description=("Demonstrates DynamicPipeline — middleware-like stage composition for agent request preprocessing."),
)


@app.agent_endpoint(
    name="order.place",
    description="Place an order — pipeline stages run before the handler",
    response_model=OrderResponse,
)
async def place_order(intent: Intent, context: AgentContext) -> OrderResponse:
    """Place an order after running the pipeline.

    The handler decides *at runtime* which available stages to select
    based on the intent content — if the user mentions a geographic
    region, we add geo_enrichment + discount_calculator.
    """
    # Decide which optional stages to add.
    intent_lower = intent.raw.lower()
    region_mentioned = any(kw in intent_lower for kw in _REGIONS)
    selected = ["geo_enrichment", "discount_calculator"] if region_mentioned else []

    # Build the initial context for the pipeline.
    initial_ctx: dict[str, Any] = {
        "intent_text": intent.raw,
        "session_id": context.session_id or "anonymous",
    }

    # Run the pipeline. Base stages always execute; selected stages
    # are added on top, sorted by order.
    result = await pipeline.execute(initial_ctx, selected_stages=selected)

    # Extract a simple item + quantity from the intent.
    words = intent.raw.split()
    quantity = 1
    for w in words:
        if w.isdigit():
            quantity = int(w)
            break
    item_candidates = [
        w
        for w in words
        if len(w) > 3 and w.isalpha() and w.lower() not in {"place", "order", "item", "items", "that", "this", "with"}
    ]
    item = item_candidates[-1] if item_candidates else "widget"

    return OrderResponse(
        order_id=result.context.get("request_id", "?"),
        item=item,
        quantity=max(quantity, 1),
        discount_pct=result.context.get("discount_pct", 0.0),
        region=result.context.get("region", "GLOBAL"),
        rate_limited=result.context.get("rate_limited", False),
        request_count=result.context.get("request_count", 0),
        stages_executed=result.stages_executed,
        stage_timings_ms={k: round(v, 2) for k, v in result.stage_timings_ms.items()},
    )


@app.agent_endpoint(
    name="pipeline.info",
    description="Report the pipeline configuration",
    response_model=PipelineInfoResponse,
)
async def pipeline_info(intent: Intent, context: AgentContext) -> PipelineInfoResponse:
    """Show which stages are configured and how the pipeline is wired."""
    return PipelineInfoResponse(
        base_stages=[s.name for s in pipeline.base_stages],
        available_stages=pipeline.available_stage_names,
        max_stages=8,
    )
