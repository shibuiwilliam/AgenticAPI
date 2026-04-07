"""Tests for AgenticApp."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from httpx import ASGITransport, AsyncClient

from agenticapi.app import AgenticApp
from agenticapi.exceptions import (
    CodeExecutionError,
    IntentParseError,
    PolicyViolation,
    SandboxViolation,
    ToolError,
)
from agenticapi.routing import AgentRouter

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


def _make_handler(result: Any = None):
    """Create a simple sync handler returning a fixed result."""

    def handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
        return result or {"count": 42}

    return handler


class TestAgenticAppCreation:
    def test_defaults(self) -> None:
        app = AgenticApp()
        assert app.title == "AgenticAPI"
        assert app.version == "0.1.0"
        assert app.harness is None

    def test_custom_title_and_version(self) -> None:
        app = AgenticApp(title="My Service", version="1.2.3")
        assert app.title == "My Service"
        assert app.version == "1.2.3"


class TestAgentEndpointDecorator:
    def test_registers_endpoint(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        async def order_agent(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {"ok": True}

        assert "orders" in app._endpoints
        assert app._endpoints["orders"].name == "orders"
        assert app._endpoints["orders"].handler is order_agent

    def test_decorator_returns_original_function(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="test")
        async def my_func(intent: Intent, context: AgentContext) -> None:
            pass

        assert callable(my_func)

    def test_endpoint_with_description(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="products", description="Product agent")
        async def product_agent(intent: Intent, context: AgentContext) -> None:
            pass

        assert app._endpoints["products"].description == "Product agent"


class TestIncludeRouter:
    def test_merges_endpoints(self) -> None:
        app = AgenticApp()
        router = AgentRouter(prefix="orders")

        @router.agent_endpoint(name="query")
        async def order_query(intent: Intent, context: AgentContext) -> None:
            pass

        app.include_router(router)
        assert "orders.query" in app._endpoints

    def test_include_router_with_prefix(self) -> None:
        app = AgenticApp()
        router = AgentRouter()

        @router.agent_endpoint(name="items")
        async def items_handler(intent: Intent, context: AgentContext) -> None:
            pass

        app.include_router(router, prefix="shop")
        assert "shop.items" in app._endpoints

    def test_include_router_without_prefix(self) -> None:
        app = AgenticApp()
        router = AgentRouter()

        @router.agent_endpoint(name="plain")
        async def plain_handler(intent: Intent, context: AgentContext) -> None:
            pass

        app.include_router(router)
        assert "plain" in app._endpoints


class TestHealthEndpoint:
    async def test_health_returns_200(self) -> None:
        app = AgenticApp(version="2.0.0")

        @app.agent_endpoint(name="dummy")
        async def dummy(intent: Intent, context: AgentContext) -> None:
            pass

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "2.0.0"
        assert "endpoints" in data


class TestCapabilitiesEndpoint:
    async def test_capabilities_returns_endpoint_metadata(self) -> None:
        from agenticapi.interface.intent import IntentScope

        app = AgenticApp(title="TestApp", version="1.0.0")

        @app.agent_endpoint(
            name="orders",
            description="Query orders",
            autonomy_level="auto",
            intent_scope=IntentScope(allowed_intents=["order.*"]),
        )
        async def handler(intent: Intent, context: AgentContext) -> None:
            pass

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/capabilities")

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "TestApp"
        assert len(data["endpoints"]) == 1
        ep = data["endpoints"][0]
        assert ep["name"] == "orders"
        assert ep["description"] == "Query orders"
        assert ep["autonomy_level"] == "auto"
        assert "order.*" in ep["intent_scope"]["allowed_intents"]


class TestAgentEndpointHTTP:
    async def test_post_valid_intent(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        def order_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {"order_count": 42}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agent/orders",
                json={"intent": "show me orders"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"] == {"order_count": 42}

    async def test_post_unknown_endpoint_returns_404(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        def order_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agent/nonexistent",
                json={"intent": "hello"},
            )

        assert response.status_code == 404

    async def test_post_missing_intent_returns_400(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        def order_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agent/orders",
                json={"not_intent": "hello"},
            )

        assert response.status_code == 400

    async def test_post_invalid_json_returns_400(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        def order_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agent/orders",
                content=b"not json",
                headers={"content-type": "application/json"},
            )

        assert response.status_code == 400


class TestHTTPErrorStatusCodes:
    """Test that each exception type maps to the correct HTTP status code."""

    async def _post_to_throwing_endpoint(self, exc: Exception) -> int:
        """Create an app with a handler that raises exc, return HTTP status."""
        app = AgenticApp()

        @app.agent_endpoint(name="throw")
        def handler(intent: Intent, context: AgentContext) -> None:
            raise exc

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/throw", json={"intent": "test"})
        return response.status_code

    async def test_policy_violation_returns_403(self) -> None:
        status = await self._post_to_throwing_endpoint(PolicyViolation(policy="test", violation="blocked"))
        assert status == 403

    async def test_intent_parse_error_returns_400(self) -> None:
        status = await self._post_to_throwing_endpoint(IntentParseError("bad input"))
        assert status == 400

    async def test_sandbox_violation_returns_403(self) -> None:
        status = await self._post_to_throwing_endpoint(SandboxViolation("unsafe"))
        assert status == 403

    async def test_code_execution_error_returns_500(self) -> None:
        status = await self._post_to_throwing_endpoint(CodeExecutionError("crash"))
        assert status == 500

    async def test_tool_error_returns_502(self) -> None:
        status = await self._post_to_throwing_endpoint(ToolError("db down"))
        assert status == 502

    async def test_generic_handler_exception_returns_200_with_error_status(self) -> None:
        """Non-AgenticAPIError exceptions from handlers are caught and returned as error responses."""
        app = AgenticApp()

        @app.agent_endpoint(name="throw")
        def handler(intent: Intent, context: AgentContext) -> None:
            raise RuntimeError("unexpected")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/throw", json={"intent": "test"})

        # Handler exceptions are caught and returned as 200 with error status
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "unexpected" in data["error"]
