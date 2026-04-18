"""Harness-governed MCP tool server.

Exposes registered ``@tool`` functions as MCP tools with full harness
governance: policies, audit, budget, and approval applied to every
external tool call from AI assistants (Claude Code, Cursor, etc.).

Usage::

    from agenticapi import AgenticApp, tool, HarnessEngine
    from agenticapi.mcp_tools import HarnessMCPServer

    @tool(description="Query orders")
    async def query_orders(sql: str) -> list[dict]:
        ...

    app = AgenticApp(harness=HarnessEngine(policies=[...]), tools=ToolRegistry([query_orders]))
    mcp = HarnessMCPServer(app, path="/mcp/tools")

Requires ``pip install agentharnessapi[mcp]``.
"""

from __future__ import annotations

from agenticapi.mcp_tools.server import HarnessMCPServer

__all__ = ["HarnessMCPServer"]
