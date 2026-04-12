"""MCP (Model Context Protocol) compatibility layer for agent endpoints.

Generates an MCP server from agent endpoints where ``enable_mcp=True``,
allowing the same agent to be accessed as MCP tools by LLM clients
(Claude Desktop, Cursor, etc.) via the streamable-http transport.

Requires the optional ``mcp`` package::

    pip install agentharnessapi[mcp]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agenticapi.app import AgenticApp
    from agenticapi.interface.endpoint import AgentEndpointDef

logger = structlog.get_logger(__name__)

# Guard the optional dependency — mcp is an optional extra (pip install agentharnessapi[mcp])
try:
    from mcp.server.fastmcp import FastMCP as _FastMCP
except ImportError:
    _FastMCP = None  # type: ignore[assignment, misc, no-redef]


class MCPCompat:
    """Generate an MCP server from agent endpoints.

    Wraps each endpoint where ``enable_mcp=True`` as an MCP tool.
    The tool accepts an ``intent`` string and optional ``session_id``,
    then delegates to ``app.process_intent()``.

    Example:
        app = AgenticApp()

        @app.agent_endpoint(name="orders", enable_mcp=True)
        async def orders_agent(intent, context):
            ...

        mcp_app = expose_as_mcp(app, path="/mcp")
        # MCP server is now accessible at POST /mcp via streamable-http transport
    """

    def __init__(self, app: AgenticApp, *, name: str | None = None) -> None:
        """Initialize MCP compatibility layer.

        Args:
            app: The AgenticApp to generate MCP tools for.
            name: Optional name for the MCP server. Defaults to app.title.

        Raises:
            ImportError: If the ``mcp`` package is not installed.
        """
        if _FastMCP is None:
            raise ImportError(
                "The 'mcp' package is required for MCP support. Install it with: pip install agentharnessapi[mcp]"
            )
        self._app = app
        self._name = name or app.title
        self._mcp: Any = None  # FastMCP instance, typed as Any to avoid import issues

    def build_server(self) -> Any:
        """Build the FastMCP server with tools for all MCP-enabled endpoints.

        The server is configured with ``streamable_http_path="/"`` so that
        when its ASGI app is mounted at a path (e.g. ``/mcp``), the protocol
        endpoint is reachable at that exact path — not at ``<mount>/mcp``.

        Returns:
            A configured FastMCP server instance.
        """
        assert _FastMCP is not None
        # streamable_http_path="/" makes the inner app serve at root, so
        # mounting at "/mcp" gives the user the URL they expect: /mcp.
        mcp = _FastMCP(self._name, streamable_http_path="/")

        mcp_endpoints = {name: ep for name, ep in self._app._endpoints.items() if ep.enable_mcp}

        for ep_name, endpoint_def in mcp_endpoints.items():
            self._register_tool(mcp, ep_name, endpoint_def)

        logger.info(
            "mcp_tools_registered",
            tool_count=len(mcp_endpoints),
            total_endpoints=len(self._app._endpoints),
        )

        self._mcp = mcp
        return mcp

    def _register_tool(
        self,
        mcp: Any,
        ep_name: str,
        endpoint_def: AgentEndpointDef,
    ) -> None:
        """Register a single MCP tool for an agent endpoint.

        Uses a separate method (not inline in the loop) to ensure the closure
        captures ``ep_name`` correctly via the method parameter.

        Args:
            mcp: The FastMCP server to register on.
            ep_name: The endpoint name (becomes the tool name).
            endpoint_def: The AgentEndpointDef for this endpoint.
        """
        app = self._app
        description = endpoint_def.description or f"Agent endpoint: {ep_name}"

        @mcp.tool(name=ep_name, description=description)  # type: ignore[untyped-decorator]
        async def tool_handler(intent: str, session_id: str | None = None) -> str:
            """Process a natural language intent through the agent endpoint.

            Args:
                intent: Natural language request to process.
                session_id: Optional session ID for multi-turn conversations.

            Returns:
                JSON string with the agent response.
            """
            from agenticapi.exceptions import AgenticAPIError

            try:
                response = await app.process_intent(
                    intent,
                    endpoint_name=ep_name,
                    session_id=session_id,
                )
                from starlette.responses import Response as StarletteResponse

                if isinstance(response, StarletteResponse):
                    return json.dumps({"status": "completed", "result": "(file response)"})

                from agenticapi.interface.response import ResponseFormatter

                formatter = ResponseFormatter()
                return json.dumps(formatter.format_json(response))
            except AgenticAPIError as exc:
                return json.dumps({"status": "error", "error": str(exc)})

    def streamable_http_app(self) -> Any:
        """Return a Starlette-mountable ASGI app for the MCP server.

        Builds the server if not already built.

        Returns:
            A Starlette ASGI application for the streamable-http transport.
        """
        if self._mcp is None:
            self.build_server()
        return self._mcp.streamable_http_app()


def expose_as_mcp(app: AgenticApp, *, path: str = "/mcp") -> None:
    """Mount an MCP server on the AgenticApp.

    Generates MCP tools from all endpoints where ``enable_mcp=True``
    and mounts the MCP server at the specified path using
    the streamable-http transport.

    Args:
        app: The AgenticApp to generate MCP tools for.
        path: URL path prefix for the MCP server.

    Raises:
        ImportError: If the ``mcp`` package is not installed.
    """
    from starlette.routing import Mount

    compat = MCPCompat(app)
    mcp_asgi_app = compat.streamable_http_app()

    mount = Mount(path, app=mcp_asgi_app)
    app.add_routes([mount])

    # Starlette doesn't propagate lifespan events to mounted sub-apps, so we
    # must register FastMCP's lifespan explicitly. Without this, the
    # StreamableHTTPSessionManager is never started and every request fails
    # with "Task group is not initialized".
    app.add_lifespan(lambda: mcp_asgi_app.router.lifespan_context(mcp_asgi_app))

    logger.info("mcp_server_mounted", path=path)
