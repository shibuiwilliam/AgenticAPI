"""Integration test: full flow from HTTP request to response."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from httpx import ASGITransport, AsyncClient

from agenticapi.app import AgenticApp

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


class TestEndpointFlow:
    async def test_full_flow_handler_based(self) -> None:
        """POST /agent/{name} -> intent parse -> handler -> response."""
        app = AgenticApp(title="Test Service", version="0.0.1")

        @app.agent_endpoint(name="orders", description="Order management agent")
        def order_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {"order_count": 42, "action": intent.action.value}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agent/orders",
                json={"intent": "show me all orders"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"]["order_count"] == 42
        assert data["result"]["action"] == "read"

    async def test_flow_with_session_id(self) -> None:
        """POST with session_id maintains session continuity."""
        app = AgenticApp()

        @app.agent_endpoint(name="chat")
        def chat_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {"message": "hello", "session": context.session_id}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                "/agent/chat",
                json={"intent": "hello", "session_id": "my-session"},
            )
            r2 = await client.post(
                "/agent/chat",
                json={"intent": "follow up", "session_id": "my-session"},
            )

        assert r1.status_code == 200
        assert r2.status_code == 200

    async def test_health_check(self) -> None:
        """GET /health returns status and version."""
        app = AgenticApp(version="1.0.0")

        @app.agent_endpoint(name="test")
        def handler(intent: Intent, context: AgentContext) -> None:
            pass

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"
        assert "test" in data["endpoints"]

    async def test_async_handler(self) -> None:
        """Async handlers are supported."""
        app = AgenticApp()

        @app.agent_endpoint(name="async_ep")
        async def async_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {"async": True}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agent/async_ep",
                json={"intent": "do something"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["async"] is True
