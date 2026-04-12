"""Anthropic (Claude) powered agent example with harness safety and custom prompts.

Demonstrates:
- AnthropicBackend for LLM-powered intent parsing and code generation
- Custom prompts: calling Claude directly with endpoint-specific system prompts
- HarnessEngine with CodePolicy, DataPolicy, and ResourcePolicy
- DatabaseTool for querying a product catalogue

Prerequisites:
    export ANTHROPIC_API_KEY="sk-ant-..."

Run with:
    uvicorn examples.04_anthropic_agent.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.04_anthropic_agent.app:app

Test with curl:
    # Search products (handler-based)
    curl -X POST http://127.0.0.1:8000/agent/products.search \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show me all electronics under 50000 yen"}'

    # LLM-powered product description (custom prompt)
    curl -X POST http://127.0.0.1:8000/agent/products.describe \
        -H "Content-Type: application/json" \
        -d '{"intent": "Write a marketing description for the Noise-Cancelling Headphones"}'

    # LLM-powered gift recommendation (custom prompt)
    curl -X POST http://127.0.0.1:8000/agent/products.recommend \
        -H "Content-Type: application/json" \
        -d '{"intent": "Suggest a gift for a software developer under 20000 yen"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

import json as _json
import os
from typing import TYPE_CHECKING, Any

from agenticapi.app import AgenticApp
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.harness.policy.resource_policy import ResourcePolicy
from agenticapi.interface.intent import Intent, IntentScope
from agenticapi.interface.response import AgentResponse
from agenticapi.routing import AgentRouter
from agenticapi.runtime.llm.anthropic import AnthropicBackend
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
from agenticapi.runtime.tools.database import DatabaseTool
from agenticapi.runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# Mock data — a product catalogue
# ---------------------------------------------------------------------------

PRODUCTS = [
    {"id": 1, "name": "Wireless Earbuds", "category": "electronics", "price": 12800, "stock": 45},
    {"id": 2, "name": "Mechanical Keyboard", "category": "electronics", "price": 18500, "stock": 22},
    {"id": 3, "name": "USB-C Hub", "category": "electronics", "price": 4980, "stock": 120},
    {"id": 4, "name": "Standing Desk", "category": "furniture", "price": 49800, "stock": 8},
    {"id": 5, "name": "Monitor Arm", "category": "furniture", "price": 6800, "stock": 35},
    {"id": 6, "name": "Python Cookbook", "category": "books", "price": 3200, "stock": 200},
    {"id": 7, "name": "Ergonomic Mouse", "category": "electronics", "price": 8900, "stock": 60},
    {"id": 8, "name": "Desk Lamp", "category": "furniture", "price": 5400, "stock": 3},
    {"id": 9, "name": "Webcam HD", "category": "electronics", "price": 7600, "stock": 15},
    {"id": 10, "name": "Noise-Cancelling Headphones", "category": "electronics", "price": 34500, "stock": 18},
]


async def mock_db_execute(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Simulate database queries against the product catalogue."""
    q = query.lower()
    if "product" in q or "catalog" in q:
        return PRODUCTS
    return []


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

db_tool = DatabaseTool(
    name="product_db",
    description=(
        "Product catalogue database with a 'products' table. "
        "Columns: id (int), name (str), category (str), price (int, in yen), stock (int)."
    ),
    execute_fn=mock_db_execute,
    read_only=True,
)

tools = ToolRegistry()
tools.register(db_tool)

# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

code_policy = CodePolicy(
    denied_modules=["os", "subprocess", "shutil", "sys", "importlib", "pathlib"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
    allow_network=False,
    max_code_lines=150,
)

data_policy = DataPolicy(
    readable_tables=["products"],
    writable_tables=[],
    restricted_columns=["cost_price", "supplier_id"],
    deny_ddl=True,
    max_result_rows=1000,
)

resource_policy = ResourcePolicy(
    max_cpu_seconds=10,
    max_memory_mb=256,
    max_execution_time_seconds=30,
)

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

harness = HarnessEngine(
    policies=[code_policy, data_policy, resource_policy],
)

# ---------------------------------------------------------------------------
# LLM backend — Anthropic Claude
# ---------------------------------------------------------------------------
#
# The backend is created lazily so the example can be imported and
# served (``/health``, ``/docs``, ``/openapi.json``, and the deterministic
# search / inventory endpoints) without ``ANTHROPIC_API_KEY`` set. The
# two custom-prompt endpoints (``describe``, ``recommend``) return a
# structured friendly error when the key is missing rather than
# crashing the handler.

llm: AnthropicBackend | None = (
    AnthropicBackend(model="claude-sonnet-4-20250514") if os.environ.get("ANTHROPIC_API_KEY") else None
)

# ---------------------------------------------------------------------------
# Routers and endpoints
# ---------------------------------------------------------------------------

products_router = AgentRouter(prefix="products", tags=["products"])


@products_router.agent_endpoint(
    name="search",
    description="Search and filter products by category, price range, name, or stock level",
    intent_scope=IntentScope(allowed_intents=["product.*", "catalog.*", "*.read", "*.analyze", "*.clarify"]),
    autonomy_level="auto",
)
async def product_search(intent: Intent, context: AgentContext) -> AgentResponse:
    """Search products with optional filters."""
    category = intent.parameters.get("category")
    max_price = intent.parameters.get("max_price")

    results = PRODUCTS
    if category:
        results = [p for p in results if p["category"] == category]
    if max_price:
        try:
            limit = int(max_price)
            results = [p for p in results if p["price"] <= limit]
        except ValueError:
            pass

    return AgentResponse(
        result={
            "products": results,
            "count": len(results),
            "categories": sorted({p["category"] for p in results}),
        },
        reasoning=f"Found {len(results)} products matching the query",
    )


@products_router.agent_endpoint(
    name="inventory",
    description="Inventory analytics: stock levels, low-stock alerts, category summaries",
    intent_scope=IntentScope(allowed_intents=["product.*", "catalog.*", "*.read", "*.analyze", "*.clarify"]),
    autonomy_level="auto",
)
async def product_inventory(intent: Intent, context: AgentContext) -> AgentResponse:
    """Analyse inventory levels across the catalogue."""
    low_stock_threshold = 10
    low_stock = [p for p in PRODUCTS if p["stock"] < low_stock_threshold]

    by_category: dict[str, dict[str, int]] = {}
    for p in PRODUCTS:
        cat = p["category"]
        by_category.setdefault(cat, {"count": 0, "total_stock": 0, "total_value": 0})
        by_category[cat]["count"] += 1
        by_category[cat]["total_stock"] += p["stock"]
        by_category[cat]["total_value"] += p["price"] * p["stock"]

    return AgentResponse(
        result={
            "total_products": len(PRODUCTS),
            "total_stock_units": sum(p["stock"] for p in PRODUCTS),
            "low_stock_items": low_stock,
            "by_category": by_category,
        },
        reasoning=f"Inventory summary with {len(low_stock)} low-stock alerts (threshold: {low_stock_threshold})",
    )


# ---------------------------------------------------------------------------
# Custom prompt endpoints — call Claude directly with specific prompts
# ---------------------------------------------------------------------------


@products_router.agent_endpoint(
    name="describe",
    description="LLM-powered marketing description for a product",
    intent_scope=IntentScope(allowed_intents=["*"]),
    autonomy_level="manual",  # bypass harness — handler calls LLM directly
)
async def product_describe(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Call Claude with a custom prompt to generate a product description."""
    if llm is None:
        return {
            "error": "ANTHROPIC_API_KEY not set",
            "detail": (
                "This endpoint calls Claude directly with a custom prompt. Set "
                "ANTHROPIC_API_KEY in the environment and restart the server to "
                "enable it. The deterministic search / inventory endpoints run "
                "without credentials."
            ),
        }

    catalog = _json.dumps(PRODUCTS, indent=2)
    prompt = LLMPrompt(
        system=(
            "You are a creative marketing copywriter. Given a product catalogue, "
            "write a compelling 2-3 sentence marketing description for the product "
            "the user asks about. Be enthusiastic but factual. Include the price."
        ),
        messages=[
            LLMMessage(role="user", content=f"Catalogue:\n{catalog}\n\nRequest: {intent.raw}"),
        ],
        temperature=0.7,
        max_tokens=256,
    )

    response = await llm.generate(prompt)
    return {"description": response.content, "model": llm.model_name}


@products_router.agent_endpoint(
    name="recommend",
    description="LLM-powered gift/purchase recommendation",
    intent_scope=IntentScope(allowed_intents=["*"]),
    autonomy_level="manual",  # bypass harness — handler calls LLM directly
)
async def product_recommend(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Call Claude with a custom prompt to recommend products."""
    if llm is None:
        return {
            "error": "ANTHROPIC_API_KEY not set",
            "detail": (
                "This endpoint calls Claude directly with a custom prompt. Set "
                "ANTHROPIC_API_KEY in the environment and restart the server to "
                "enable it. The deterministic search / inventory endpoints run "
                "without credentials."
            ),
        }

    catalog = _json.dumps(PRODUCTS, indent=2)
    prompt = LLMPrompt(
        system=(
            "You are a helpful shopping assistant. Given a product catalogue, "
            "recommend 1-3 products that best match what the user is looking for. "
            "Explain why each is a good choice. Be concise and friendly."
        ),
        messages=[
            LLMMessage(role="user", content=f"Catalogue:\n{catalog}\n\nRequest: {intent.raw}"),
        ],
        temperature=0.5,
        max_tokens=512,
    )

    response = await llm.generate(prompt)
    return {"recommendation": response.content, "model": llm.model_name}


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Product Catalogue Agent (Anthropic Claude)",
    version="0.1.0",
    llm=llm,  # type: ignore[arg-type]
    harness=harness,
    tools=tools,
)
app.include_router(products_router)
