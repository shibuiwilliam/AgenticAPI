"""Tests for MCP compatibility layer."""

from __future__ import annotations

import pytest

# Skip entire module if mcp is not installed
pytest.importorskip("mcp")

from agenticapi.app import AgenticApp
from agenticapi.interface.compat.mcp import MCPCompat, expose_as_mcp
from agenticapi.interface.endpoint import AgentEndpointDef
from agenticapi.routing import AgentRouter

# ---------------------------------------------------------------------------
# enable_mcp field propagation
# ---------------------------------------------------------------------------


class TestEnableMCPField:
    """Test that enable_mcp flows through the decorator and router chains."""

    def test_endpoint_def_stores_enable_mcp_true(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders", enable_mcp=True)
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        assert app._endpoints["orders"].enable_mcp is True

    def test_endpoint_def_defaults_enable_mcp_false(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        assert app._endpoints["orders"].enable_mcp is False

    def test_router_endpoint_stores_enable_mcp(self) -> None:
        router = AgentRouter(prefix="api")

        @router.agent_endpoint(name="items", enable_mcp=True)
        async def items_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        assert router.endpoints["api.items"].enable_mcp is True

    def test_include_router_preserves_enable_mcp(self) -> None:
        app = AgenticApp()
        router = AgentRouter(prefix="api")

        @router.agent_endpoint(name="items", enable_mcp=True)
        async def items_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        @router.agent_endpoint(name="internal")
        async def internal_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        app.include_router(router)

        assert app._endpoints["api.items"].enable_mcp is True
        assert app._endpoints["api.internal"].enable_mcp is False

    def test_dataclass_field_default(self) -> None:
        ep = AgentEndpointDef(name="test", handler=lambda: None)
        assert ep.enable_mcp is False


# ---------------------------------------------------------------------------
# MCPCompat
# ---------------------------------------------------------------------------


class TestMCPCompat:
    """Test MCPCompat server creation and tool registration."""

    def test_build_server_registers_only_mcp_enabled_endpoints(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders", description="Order queries", enable_mcp=True)
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"count": 42}

        @app.agent_endpoint(name="internal", description="Internal only")
        async def internal_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        compat = MCPCompat(app)
        server = compat.build_server()
        tools = server._tool_manager.list_tools()
        tool_names = [t.name for t in tools]

        assert "orders" in tool_names
        assert "internal" not in tool_names

    def test_build_server_no_mcp_endpoints_creates_empty_server(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        compat = MCPCompat(app)
        server = compat.build_server()
        tools = server._tool_manager.list_tools()
        assert len(tools) == 0

    def test_build_server_multiple_mcp_endpoints(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders", description="Query orders", enable_mcp=True)
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        @app.agent_endpoint(name="products", description="Query products", enable_mcp=True)
        async def products_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        compat = MCPCompat(app)
        server = compat.build_server()
        tools = server._tool_manager.list_tools()
        tool_names = {t.name for t in tools}

        assert tool_names == {"orders", "products"}

    def test_tool_description_uses_endpoint_description(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders", description="Query order information", enable_mcp=True)
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        compat = MCPCompat(app)
        server = compat.build_server()
        tools = server._tool_manager.list_tools()
        assert tools[0].description == "Query order information"

    def test_tool_description_fallback_when_empty(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="orders", enable_mcp=True)
        async def orders_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        compat = MCPCompat(app)
        server = compat.build_server()
        tools = server._tool_manager.list_tools()
        assert "orders" in tools[0].description

    def test_streamable_http_app_returns_callable(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="test", enable_mcp=True)
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"ok": True}

        compat = MCPCompat(app)
        asgi_app = compat.streamable_http_app()
        assert callable(asgi_app)

    def test_streamable_http_app_auto_builds_server(self) -> None:
        """streamable_http_app() calls build_server() lazily if not already built."""
        app = AgenticApp()

        @app.agent_endpoint(name="test", enable_mcp=True)
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        compat = MCPCompat(app)
        assert compat._mcp is None
        compat.streamable_http_app()
        assert compat._mcp is not None

    def test_default_server_name_uses_app_title(self) -> None:
        app = AgenticApp(title="My App")
        compat = MCPCompat(app)
        assert compat._name == "My App"

    def test_custom_server_name(self) -> None:
        app = AgenticApp(title="My App")
        compat = MCPCompat(app, name="Custom MCP Server")
        assert compat._name == "Custom MCP Server"


# ---------------------------------------------------------------------------
# expose_as_mcp convenience function
# ---------------------------------------------------------------------------


class TestExposeAsMCP:
    """Test the expose_as_mcp convenience function."""

    def test_expose_as_mcp_adds_mount_to_app(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="test", enable_mcp=True)
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"ok": True}

        expose_as_mcp(app, path="/mcp")
        assert len(app._extra_routes) == 1
        # Force rebuild was triggered
        assert app._starlette_app is None

    def test_expose_as_mcp_custom_path(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="test", enable_mcp=True)
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        expose_as_mcp(app, path="/v1/mcp")
        from starlette.routing import Mount

        mount = app._extra_routes[0]
        assert isinstance(mount, Mount)
        assert mount.path == "/v1/mcp"

    def test_expose_as_mcp_default_path(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="test", enable_mcp=True)
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {}

        expose_as_mcp(app)
        from starlette.routing import Mount

        mount = app._extra_routes[0]
        assert isinstance(mount, Mount)
        assert mount.path == "/mcp"


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


class TestMCPImportGuard:
    """Test behavior when mcp package is not available."""

    def test_import_error_raised_without_mcp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MCPCompat raises ImportError when mcp is not installed."""
        import agenticapi.interface.compat.mcp as mcp_module

        original = mcp_module._FastMCP
        try:
            mcp_module._FastMCP = None  # type: ignore[assignment]
            app = AgenticApp()
            with pytest.raises(ImportError, match="mcp"):
                MCPCompat(app)
        finally:
            mcp_module._FastMCP = original

    def test_expose_as_mcp_raises_without_mcp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """expose_as_mcp raises ImportError when mcp is not installed."""
        import agenticapi.interface.compat.mcp as mcp_module

        original = mcp_module._FastMCP
        try:
            mcp_module._FastMCP = None  # type: ignore[assignment]
            app = AgenticApp()
            with pytest.raises(ImportError, match="mcp"):
                expose_as_mcp(app)
        finally:
            mcp_module._FastMCP = original


# ---------------------------------------------------------------------------
# Integration: MCP tool handler calls process_intent
# ---------------------------------------------------------------------------


class TestMCPToolHandler:
    """Test that MCP tool handlers correctly delegate to process_intent."""

    async def test_tool_handler_calls_process_intent(self) -> None:
        """The registered MCP tool calls app.process_intent and returns JSON."""
        app = AgenticApp()

        @app.agent_endpoint(name="echo", description="Echo back", enable_mcp=True)
        async def echo_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"echoed": intent.raw}

        compat = MCPCompat(app)
        server = compat.build_server()

        # Invoke the tool directly via the tool manager
        import json

        result = await server._tool_manager.call_tool("echo", {"intent": "hello world"})
        # call_tool returns a string (the JSON response from the tool handler)
        text = result if isinstance(result, str) else result[0].text
        data = json.loads(text)
        assert data["status"] == "completed"
        assert "echoed" in str(data["result"])

    async def test_tool_handler_with_session_id(self) -> None:
        """The tool handler passes session_id through to process_intent."""
        app = AgenticApp()

        @app.agent_endpoint(name="test", enable_mcp=True)
        async def test_agent(intent, context):  # type: ignore[no-untyped-def]
            return {"session": context.session_id}

        compat = MCPCompat(app)
        server = compat.build_server()

        import json

        result = await server._tool_manager.call_tool("test", {"intent": "hello", "session_id": "sess-123"})
        text = result if isinstance(result, str) else result[0].text
        data = json.loads(text)
        assert data["status"] == "completed"
