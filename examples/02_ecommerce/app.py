"""Ecommerce example: multi-endpoint app with harness, policies, and tools.

Demonstrates:
- Multiple agent endpoints via AgentRouter
- CodePolicy, DataPolicy for security
- ApprovalWorkflow for write operations
- DatabaseTool for data access
- Session management for multi-turn conversations

Run with:
    agenticapi dev --app examples.02_ecommerce.app:app

Or test programmatically:
    from examples.02_ecommerce.app import app
    response = await app.process_intent("show recent orders")
"""

from __future__ import annotations

from typing import Any

from agenticapi.app import AgenticApp
from agenticapi.harness.approval.rules import ApprovalRule
from agenticapi.harness.approval.workflow import ApprovalWorkflow
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.interface.intent import Intent, IntentScope
from agenticapi.interface.response import AgentResponse
from agenticapi.routing import AgentRouter
from agenticapi.runtime.context import AgentContext
from agenticapi.runtime.tools.database import DatabaseTool
from agenticapi.runtime.tools.cache import CacheTool
from agenticapi.runtime.tools.registry import ToolRegistry

# --- Mock data ---

ORDERS = [
    {"id": 1, "customer": "Alice", "total": 15000, "status": "completed"},
    {"id": 2, "customer": "Bob", "total": 8500, "status": "processing"},
    {"id": 3, "customer": "Charlie", "total": 22000, "status": "completed"},
    {"id": 4, "customer": "Diana", "total": 3200, "status": "cancelled"},
    {"id": 5, "customer": "Eve", "total": 45000, "status": "completed"},
]

PRODUCTS = [
    {"id": 1, "name": "Laptop", "price": 120000, "stock": 15, "category": "electronics"},
    {"id": 2, "name": "Headphones", "price": 8500, "stock": 50, "category": "electronics"},
    {"id": 3, "name": "Book: Python", "price": 3200, "stock": 100, "category": "books"},
    {"id": 4, "name": "Keyboard", "price": 15000, "stock": 30, "category": "electronics"},
    {"id": 5, "name": "Monitor", "price": 45000, "stock": 8, "category": "electronics"},
]


async def mock_db_execute(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Mock database execution for the example."""
    query_lower = query.lower()
    if "orders" in query_lower:
        return ORDERS
    elif "products" in query_lower:
        return PRODUCTS
    return []


# --- Tools ---

db_tool = DatabaseTool(
    name="ecommerce_db",
    description="Ecommerce database with orders and products tables",
    execute_fn=mock_db_execute,
    read_only=True,
)

cache_tool = CacheTool(
    name="ecommerce_cache",
    description="Cache for frequently accessed data",
    default_ttl_seconds=300,
)

tools = ToolRegistry()
tools.register(db_tool)
tools.register(cache_tool)

# --- Policies ---

code_policy = CodePolicy(
    denied_modules=["os", "subprocess", "shutil", "sys", "importlib"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
    allow_network=False,
)

data_policy = DataPolicy(
    readable_tables=["orders", "products", "customers"],
    writable_tables=["orders", "cart"],
    restricted_columns=["password_hash", "ssn", "credit_card"],
    deny_ddl=True,
    max_result_rows=1000,
)

# --- Approval ---

approval_workflow = ApprovalWorkflow(
    rules=[
        ApprovalRule(
            name="write_approval",
            require_for_actions=["write", "execute"],
            require_for_domains=["order"],
            approvers=["order_admin"],
            timeout_seconds=1800,
        ),
    ]
)

# --- Harness ---

harness = HarnessEngine(
    policies=[code_policy, data_policy],
    approval_workflow=approval_workflow,
)

# --- Routers ---

orders_router = AgentRouter(prefix="orders", tags=["orders"])
products_router = AgentRouter(prefix="products", tags=["products"])


@orders_router.agent_endpoint(
    name="query",
    description="Query order information: list, search, count, statistics",
    intent_scope=IntentScope(allowed_intents=["order.*"]),
    autonomy_level="auto",
)
async def order_query(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Handle order query requests."""
    action = intent.action.value
    if action == "read":
        return {
            "orders": ORDERS,
            "total_count": len(ORDERS),
            "total_revenue": sum(o["total"] for o in ORDERS),
        }
    elif action == "analyze":
        completed = [o for o in ORDERS if o["status"] == "completed"]
        return {
            "analysis": {
                "completed_orders": len(completed),
                "completion_rate": len(completed) / len(ORDERS),
                "average_order_value": sum(o["total"] for o in ORDERS) / len(ORDERS),
            }
        }
    return {"message": f"Order query: {intent.raw}", "action": action}


@orders_router.agent_endpoint(
    name="update",
    description="Update order status, cancel orders",
    intent_scope=IntentScope(
        allowed_intents=["order.write", "order.execute"],
        denied_intents=["order.bulk_delete"],
    ),
    autonomy_level="supervised",
)
async def order_update(intent: Intent, context: AgentContext) -> dict[str, str]:
    """Handle order update requests (would require approval in harness mode)."""
    return {"message": f"Order update requested: {intent.raw}", "status": "pending_review"}


@products_router.agent_endpoint(
    name="search",
    description="Search and browse products",
    autonomy_level="auto",
)
async def product_search(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Handle product search requests."""
    return {
        "products": PRODUCTS,
        "total": len(PRODUCTS),
        "categories": list({p["category"] for p in PRODUCTS}),
    }


@products_router.agent_endpoint(
    name="analytics",
    description="Product analytics: pricing, inventory, trends",
    autonomy_level="auto",
)
async def product_analytics(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Handle product analytics requests."""
    total_stock = sum(p["stock"] for p in PRODUCTS)
    avg_price = sum(p["price"] for p in PRODUCTS) / len(PRODUCTS)
    low_stock = [p for p in PRODUCTS if p["stock"] < 10]

    return {
        "analytics": {
            "total_products": len(PRODUCTS),
            "total_stock": total_stock,
            "average_price": avg_price,
            "low_stock_items": low_stock,
        }
    }


# --- App ---

app = AgenticApp(title="Ecommerce Agent", version="0.1.0")
app.include_router(orders_router)
app.include_router(products_router)
