"""Integration tests for the DX enhancements (Phase D + E + A4).

Exercises ``Depends`` + ``response_model`` + ``@tool`` together
through a real ``AgenticApp`` driven by ``TestClient``. These tests
prove the new public API actually works end-to-end, not just in
isolation.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from agenticapi import (
    AgenticApp,
    BudgetExceeded,
    BudgetPolicy,
    Depends,
    PricingRegistry,
    tool,
)
from agenticapi.harness.policy.budget_policy import BudgetEvaluationContext

# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class Order(BaseModel):
    order_id: int
    status: str
    total: float


class OrderList(BaseModel):
    orders: list[Order]
    total: int = Field(description="Number of orders returned.")


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_db_connection() -> str:
    """Return a fake DB connection identifier."""
    return "primary-db-connection"


async def get_async_resource() -> dict[str, Any]:
    return {"acquired": True, "id": "res-1"}


def get_request_id() -> str:
    return "req-12345"


# ---------------------------------------------------------------------------
# @tool decorated functions
# ---------------------------------------------------------------------------


@tool(description="List orders matching a status filter")
async def list_orders_tool(status: str = "open", limit: int = 10) -> list[dict[str, Any]]:
    return [{"order_id": i, "status": status, "total": 99.99 * i} for i in range(1, min(limit, 5) + 1)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDependsInHandler:
    def test_handler_receives_injected_dependency(self) -> None:
        """A handler with `Depends(get_db_connection)` receives the value."""
        app = AgenticApp(title="dx-test")

        @app.agent_endpoint(name="orders.query", autonomy_level="auto")
        async def query(intent, context, db: str = Depends(get_db_connection)):
            return {"db": db, "intent": intent.raw}

        client = TestClient(app)
        response = client.post("/agent/orders.query", json={"intent": "show orders"})
        assert response.status_code == 200
        body = response.json()
        # The handler returned a dict; the framework wraps it in AgentResponse.
        assert body["status"] == "completed"
        assert body["result"]["db"] == "primary-db-connection"
        assert body["result"]["intent"] == "show orders"

    def test_dependency_overrides_in_test(self) -> None:
        """``app.dependency_overrides`` substitutes a real dep with a fake."""
        app = AgenticApp(title="dx-test")

        @app.agent_endpoint(name="orders.query", autonomy_level="auto")
        async def query(intent, context, db: str = Depends(get_db_connection)):
            del intent, context
            return {"db": db}

        app.dependency_overrides[get_db_connection] = lambda: "fake-db"
        client = TestClient(app)
        response = client.post("/agent/orders.query", json={"intent": "x"})
        assert response.json()["result"]["db"] == "fake-db"
        app.dependency_overrides.clear()

    def test_async_dependency(self) -> None:
        """Async dependencies are awaited and injected."""
        app = AgenticApp(title="dx-test")

        @app.agent_endpoint(name="resources.query", autonomy_level="auto")
        async def query(intent, context, res: dict[str, Any] = Depends(get_async_resource)):
            del intent, context
            return res

        client = TestClient(app)
        body = client.post("/agent/resources.query", json={"intent": "x"}).json()
        assert body["result"]["acquired"] is True
        assert body["result"]["id"] == "res-1"


class TestResponseModel:
    def test_response_model_validates_dict(self) -> None:
        """A handler returning a dict is coerced through `response_model`."""
        app = AgenticApp(title="dx-test")

        @app.agent_endpoint(
            name="orders.list",
            autonomy_level="auto",
            response_model=OrderList,
        )
        async def list_orders(intent, context):
            del intent, context
            return {
                "orders": [{"order_id": 1, "status": "open", "total": 100.0}],
                "total": 1,
            }

        client = TestClient(app)
        body = client.post("/agent/orders.list", json={"intent": "x"}).json()
        assert body["status"] == "completed"
        # Result is now the validated, dumped OrderList.
        assert body["result"]["total"] == 1
        assert body["result"]["orders"][0]["order_id"] == 1
        assert body["result"]["orders"][0]["total"] == 100.0

    def test_openapi_publishes_response_model_schema(self) -> None:
        """The OpenAPI schema references the response_model under components."""
        app = AgenticApp(title="dx-test")

        @app.agent_endpoint(
            name="orders.list",
            autonomy_level="auto",
            response_model=OrderList,
        )
        async def list_orders(intent, context):
            del intent, context
            return {"orders": [], "total": 0}

        client = TestClient(app)
        schema = client.get("/openapi.json").json()
        assert "components" in schema
        assert "OrderList" in schema["components"]["schemas"]
        # The 200 response shape should reference the OrderList.
        op = schema["paths"]["/agent/orders.list"]["post"]
        success = op["responses"]["200"]["content"]["application/json"]["schema"]
        result_schema = success["properties"]["result"]
        assert result_schema == {"$ref": "#/components/schemas/OrderList"}

    def test_response_model_invalid_handler_return_raises_500(self) -> None:
        """A handler returning a shape that fails validation surfaces an error."""
        app = AgenticApp(title="dx-test")

        @app.agent_endpoint(
            name="orders.broken",
            autonomy_level="auto",
            response_model=OrderList,
        )
        async def broken(intent, context):
            del intent, context
            return {"not_orders": "junk"}  # missing required keys

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/agent/orders.broken", json={"intent": "x"})
        assert response.status_code == 500


class TestToolDecoratorEndToEnd:
    async def test_decorated_tool_validates_kwargs(self) -> None:
        """The @tool decorator's invoke validates inputs."""
        result = await list_orders_tool.invoke(status="shipped", limit=3)
        assert len(result) == 3
        assert all(o["status"] == "shipped" for o in result)

    def test_decorated_tool_in_registry(self) -> None:
        """Decorated tools register cleanly via plain function shortcut."""
        from agenticapi.runtime.tools import ToolRegistry

        registry = ToolRegistry()
        registry.register(list_orders_tool)
        assert "list_orders_tool" in registry


class TestBudgetPolicyIntegration:
    def test_budget_exceeded_maps_to_402(self) -> None:
        """Triggering the budget at the framework boundary returns HTTP 402."""
        app = AgenticApp(title="dx-test")
        pricing = PricingRegistry()
        pricing.set("test", input_usd_per_1k=10.0, output_usd_per_1k=10.0)
        budget = BudgetPolicy(pricing=pricing, max_per_request_usd=0.001)

        @app.agent_endpoint(name="orders.budget_demo", autonomy_level="auto")
        async def demo(intent, context):
            del context
            # Manually invoke the budget check the way the framework
            # would once Phase A wires it into the LLM call site.
            ctx = BudgetEvaluationContext(
                endpoint_name="orders.budget_demo",
                session_id=None,
                user_id=None,
                model="test",
                input_tokens=1000,
                max_output_tokens=10,
            )
            try:
                budget.estimate_and_enforce(ctx)
            except BudgetExceeded:
                raise
            return {"intent": intent.raw}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/agent/orders.budget_demo", json={"intent": "x"})
        # 402 Payment Required for budget violations.
        assert response.status_code == 402
        body = response.json()
        assert body["status"] == "error"
        assert "Budget exceeded" in body["error"]


@pytest.mark.parametrize(
    "intent_text",
    ["short", "a much longer intent that still parses cleanly into the framework"],
)
class TestBackwardCompatibility:
    def test_legacy_intent_context_handler_still_works(self, intent_text: str) -> None:
        """Existing handlers with no annotations or Depends still work."""
        app = AgenticApp(title="legacy")

        @app.agent_endpoint(name="legacy.echo", autonomy_level="auto")
        async def echo(intent, context):
            return {"echo": intent.raw, "endpoint": context.endpoint_name}

        client = TestClient(app)
        body = client.post("/agent/legacy.echo", json={"intent": intent_text}).json()
        assert body["result"]["echo"] == intent_text
        assert body["result"]["endpoint"] == "legacy.echo"
