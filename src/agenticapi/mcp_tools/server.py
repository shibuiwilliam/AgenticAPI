"""Harness-governed MCP tool server implementation.

Exposes ``ToolRegistry`` entries as MCP tools.  Every tool call from
an external AI assistant goes through the full harness pipeline:

1. ``PromptInjectionPolicy`` scans tool arguments.
2. Other policies (``DataPolicy``, ``CodePolicy``, etc.) evaluate.
3. ``BudgetPolicy`` checks cost ceilings.
4. The tool executes via ``HarnessEngine.call_tool()``.
5. ``PIIPolicy`` scans the result (via ``evaluate_tool_call`` hook).
6. ``AuditRecorder`` logs the entire call.
7. The result is returned to the MCP client.

Requires the optional ``mcp`` package::

    pip install agentharnessapi[mcp]
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agenticapi.app import AgenticApp
    from agenticapi.runtime.tools.base import Tool

logger = structlog.get_logger(__name__)

# Guard the optional dependency.
try:
    from mcp.server.fastmcp import FastMCP as _FastMCP
except ImportError:
    _FastMCP = None  # type: ignore[assignment, misc]


class HarnessMCPServer:
    """MCP server that exposes registered tools with harness governance.

    Unlike :class:`~agenticapi.interface.compat.mcp.MCPCompat` (which
    exposes *agent endpoints* as MCP tools), ``HarnessMCPServer``
    exposes the *registered ``@tool`` functions* themselves.  Every
    call goes through ``HarnessEngine.call_tool()`` with policy
    evaluation, audit recording, and budget tracking.

    Example::

        from agenticapi.mcp_tools import HarnessMCPServer

        app = AgenticApp(
            harness=HarnessEngine(policies=[CodePolicy(...)]),
            tools=ToolRegistry([query_orders, search_products]),
        )
        mcp = HarnessMCPServer(app, path="/mcp/tools")

    Args:
        app: The AgenticApp whose tools and harness to use.
        path: URL path to mount the MCP server at.
    """

    def __init__(
        self,
        app: AgenticApp,
        *,
        path: str = "/mcp/tools",
    ) -> None:
        if _FastMCP is None:
            raise ImportError(
                "The 'mcp' package is required for HarnessMCPServer. Install it with: pip install agentharnessapi[mcp]"
            )
        self._app = app
        self._path = path
        self._mcp: Any = None

        self._mount()

    def _mount(self) -> None:
        """Build and mount the MCP server on the app."""
        from starlette.routing import Mount

        assert _FastMCP is not None
        mcp = _FastMCP(f"{self._app.title} Tools", streamable_http_path="/")

        if self._app._tools is None:
            logger.warning("harness_mcp_no_tools", msg="No ToolRegistry configured")
        else:
            for defn in self._app._tools.get_definitions():
                self._register_tool(mcp, defn.name)

        self._mcp = mcp
        mcp_asgi_app = mcp.streamable_http_app()

        mount = Mount(self._path, app=mcp_asgi_app)
        self._app.add_routes([mount])
        self._app.add_lifespan(lambda: mcp_asgi_app.router.lifespan_context(mcp_asgi_app))

        tool_count = len(self._app._tools.get_definitions()) if self._app._tools else 0
        logger.info(
            "harness_mcp_mounted",
            path=self._path,
            tool_count=tool_count,
        )

    def _register_tool(self, mcp: Any, tool_name: str) -> None:
        """Register a single tool from the registry as an MCP tool.

        The closure captures ``tool_name`` via the method parameter so
        that each registered handler dispatches to the correct tool.
        """
        assert self._app._tools is not None
        tool_obj: Tool = self._app._tools.get(tool_name)
        defn = tool_obj.definition
        description = defn.description or f"Tool: {tool_name}"

        app = self._app

        @mcp.tool(name=tool_name, description=description)  # type: ignore[untyped-decorator]
        async def handler(**kwargs: Any) -> str:
            """Execute a tool call through the harness pipeline."""
            from agenticapi.exceptions import AgenticAPIError

            try:
                if app._harness is not None:
                    result = await app._harness.call_tool(
                        tool=tool_obj,
                        arguments=kwargs,
                        intent_raw=f"MCP tool call: {tool_name}",
                        intent_action="execute",
                        intent_domain="mcp",
                        endpoint_name=f"mcp:{tool_name}",
                        context=None,
                    )
                    return json.dumps(result.output, default=str)
                else:
                    result = await tool_obj.invoke(**kwargs)
                    return json.dumps(result, default=str)
            except AgenticAPIError as exc:
                return json.dumps({"error": str(exc)})

    @property
    def tool_count(self) -> int:
        """Number of tools registered on this MCP server."""
        if self._app._tools is None:
            return 0
        return len(self._app._tools.get_definitions())
