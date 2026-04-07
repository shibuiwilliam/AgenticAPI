"""Tests for REST and FastAPI compatibility layers."""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.testclient import TestClient

from agenticapi.app import AgenticApp
from agenticapi.interface.compat.fastapi import mount_fastapi, mount_in_agenticapi
from agenticapi.interface.compat.rest import RESTCompat, expose_as_rest


class TestRESTCompat:
    def test_generate_routes_creates_get_and_post(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"count": 42}

        compat = RESTCompat(app, prefix="/rest")
        routes = compat.generate_routes()

        # Should have GET and POST for "orders"
        assert len(routes) == 2
        paths = [r.path for r in routes]
        assert "/rest/orders" in paths

    def test_expose_as_rest_convenience_function(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="products")
        async def product_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"items": []}

        routes = expose_as_rest(app, prefix="/api")
        assert len(routes) == 2  # GET + POST

    def test_multiple_endpoints_generate_multiple_routes(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        @app.agent_endpoint(name="products")
        async def product_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        routes = expose_as_rest(app)
        assert len(routes) == 4  # 2 endpoints * 2 methods

    def test_custom_prefix(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="items")
        async def items_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        routes = expose_as_rest(app, prefix="/v1/api")
        paths = [r.path for r in routes]
        assert all(p.startswith("/v1/api/") for p in paths)


class TestRESTCompatHTTP:
    def test_get_endpoint_responds(self) -> None:
        """GET request through REST compat returns response."""
        app = AgenticApp()

        @app.agent_endpoint(name="test")
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"message": "hello"}

        # Build a Starlette app with REST routes
        from starlette.applications import Starlette

        routes = expose_as_rest(app)
        starlette_app = Starlette(routes=routes)
        client = TestClient(starlette_app)

        response = client.get("/rest/test?query=show+items")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_post_endpoint_responds(self) -> None:
        """POST request through REST compat returns response."""
        app = AgenticApp()

        @app.agent_endpoint(name="test")
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"created": True}

        from starlette.applications import Starlette

        routes = expose_as_rest(app)
        starlette_app = Starlette(routes=routes)
        client = TestClient(starlette_app)

        response = client.post("/rest/test", json={"intent": "create order"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_post_invalid_json_returns_400(self) -> None:
        """POST with invalid JSON returns 400."""
        app = AgenticApp()

        @app.agent_endpoint(name="test")
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        from starlette.applications import Starlette

        routes = expose_as_rest(app)
        starlette_app = Starlette(routes=routes)
        client = TestClient(starlette_app)

        response = client.post(
            "/rest/test",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400


class TestMountFastAPI:
    def test_mount_fastapi_calls_mount(self) -> None:
        """mount_fastapi delegates to FastAPI's mount method."""
        agenticapi_app = AgenticApp()
        fastapi_mock = MagicMock()

        mount_fastapi(agenticapi_app, fastapi_mock, path="/agent")

        fastapi_mock.mount.assert_called_once_with("/agent", agenticapi_app)

    def test_mount_in_agenticapi_stores_sub_app(self) -> None:
        """mount_in_agenticapi stores the sub-app for later inclusion."""
        agenticapi_app = AgenticApp()
        sub_app_mock = MagicMock()

        mount_in_agenticapi(agenticapi_app, sub_app_mock, path="/api")

        assert hasattr(agenticapi_app, "_mounted_apps")
        assert len(agenticapi_app._mounted_apps) == 1  # type: ignore[attr-defined]
        assert agenticapi_app._mounted_apps[0] == ("/api", sub_app_mock)  # type: ignore[attr-defined]
