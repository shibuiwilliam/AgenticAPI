"""Anthropic (Claude) powered agent example with harness safety.

Demonstrates:
- AnthropicBackend for LLM-powered intent parsing and code generation
- HarnessEngine with CodePolicy, DataPolicy, and ResourcePolicy
- DatabaseTool for querying a product catalogue
- Full pipeline: intent -> code generation -> policy check -> sandbox -> response

Prerequisites:
    export ANTHROPIC_API_KEY="sk-ant-..."

Run with:
    uvicorn examples.04_anthropic_agent.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.04_anthropic_agent.app:app

Test with curl:
    # Search products
    curl -X POST http://127.0.0.1:8000/agent/products.search \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show me all electronics under 50000 yen"}'

    # Get inventory summary
    curl -X POST http://127.0.0.1:8000/agent/products.inventory \
        -H "Content-Type: application/json" \
        -d '{"intent": "Which products are low in stock?"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

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

llm = AnthropicBackend(model="claude-sonnet-4-20250514")

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
