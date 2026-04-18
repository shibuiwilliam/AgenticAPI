"""Example 32 — Harness-Governed MCP Tool Server.

Exposes three ``@tool`` functions as **both** regular agent endpoints
and as MCP tools (when ``agentharnessapi[mcp]`` is installed).  Every
tool call — whether it arrives from a curl command or an AI assistant
via MCP — goes through the full harness pipeline: policy evaluation,
PII scanning, and audit recording.

This example demonstrates:

- **``HarnessMCPServer``** — mounts registered ``@tool`` functions as
  MCP tools with harness governance at ``/mcp/tools``.
- **``HarnessEngine.call_tool()``** — the harness pipeline for tool
  calls: policies evaluate the tool name and arguments, the tool
  executes, and the result is audit-recorded.
- **Three policies** running on every tool call: ``CodePolicy``,
  ``DataPolicy``, ``PIIPolicy``.
- **Agent endpoints** for each tool so the example is testable without
  an MCP client.

Prerequisites (for MCP exposure only):
    pip install agentharnessapi[mcp]

Run::

    uvicorn examples.32_harness_mcp_tools.app:app --reload

Test with MCP inspector (requires ``[mcp]`` extra)::

    npx @modelcontextprotocol/inspector http://localhost:8000/mcp/tools

Test tool calls (direct HTTP — no MCP needed)::

    # Calculator
    curl -X POST http://127.0.0.1:8000/agent/tools.calculate \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "7 * 6"}'

    # Order query
    curl -X POST http://127.0.0.1:8000/agent/tools.query_orders \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "show all orders"}'

    # File read
    curl -X POST http://127.0.0.1:8000/agent/tools.read_file \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "readme.txt"}'

    # Tool catalogue
    curl -X POST http://127.0.0.1:8000/agent/tools.catalog \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "list tools"}'
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from agenticapi import AgenticApp, CodePolicy, DataPolicy, HarnessEngine, PIIPolicy
from agenticapi.runtime.tools.decorator import tool
from agenticapi.runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# Tools — exposed both as agent endpoints and as MCP tools
# ---------------------------------------------------------------------------


@tool(description="Evaluate a math expression and return the result")
async def calculator(expression: str) -> dict[str, Any]:
    """Safe calculator that evaluates simple math expressions.

    Only digits, operators (+, -, *, /), dots, parentheses, and spaces
    are allowed.  All builtins are stripped to prevent code injection.
    """
    allowed_chars = set("0123456789+-*/.() ")
    if not all(c in allowed_chars for c in expression):
        return {"error": "Only numeric expressions are allowed", "expression": expression}
    try:
        result = eval(expression, {"__builtins__": {}})
        return {"expression": expression, "result": result}
    except Exception as exc:
        return {"error": str(exc), "expression": expression}


@tool(description="Query the orders database")
async def query_orders(sql: str) -> dict[str, Any]:
    """Simulated database query against the orders table.

    Returns a fixed set of rows regardless of the SQL — this is a
    demo, not a real database.
    """
    rows = [
        {"order_id": 1, "customer": "Alice", "total": 99.99, "status": "shipped"},
        {"order_id": 2, "customer": "Bob", "total": 149.50, "status": "pending"},
        {"order_id": 3, "customer": "Carol", "total": 72.00, "status": "delivered"},
    ]
    return {"sql": sql, "rows": rows, "count": len(rows)}


@tool(description="Read a file from the allowed directory")
async def read_file(path: str) -> dict[str, Any]:
    """Simulated file reader (returns dummy content).

    Rejects path traversal (``..``) and absolute paths.
    """
    if ".." in path or path.startswith("/"):
        return {"error": "Path traversal not allowed", "path": path}
    return {"path": path, "content": f"Contents of {path}", "size_bytes": 1024}


# ---------------------------------------------------------------------------
# Harness with policies
# ---------------------------------------------------------------------------

harness = HarnessEngine(
    policies=[
        CodePolicy(denied_modules=["os", "subprocess", "shutil"]),
        DataPolicy(readable_tables=["orders"], writable_tables=[]),
        PIIPolicy(),
    ],
)

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

tools = ToolRegistry()
tools.register(calculator)
tools.register(query_orders)
tools.register(read_file)

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Harness MCP Tools",
    description=(
        "MCP tool server with harness-governed tool dispatch.  "
        "Every tool call goes through CodePolicy + DataPolicy + PIIPolicy."
    ),
    harness=harness,
    tools=tools,
)

# ---------------------------------------------------------------------------
# Agent endpoints — exercise the tools directly via HTTP
# ---------------------------------------------------------------------------

# Regex to extract a math expression from natural language
_EXPR_RE = re.compile(r"[\d+\-*/.() ]+")


@app.agent_endpoint(name="tools.calculate", description="Evaluate a math expression")
async def calc_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Extract a numeric expression from the intent and evaluate it."""
    raw = intent.raw.strip()
    # Try to extract just the math expression from the text
    match = _EXPR_RE.search(raw)
    expression = match.group().strip() if match else raw
    return await calculator(expression=expression)


@app.agent_endpoint(name="tools.query_orders", description="Query the orders table")
async def orders_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Forward the intent text as a SQL query (simulated)."""
    return await query_orders(sql=intent.raw.strip())


@app.agent_endpoint(name="tools.read_file", description="Read a file by path")
async def file_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Forward the intent text as a file path."""
    return await read_file(path=intent.raw.strip())


@app.agent_endpoint(name="tools.catalog", description="List all registered tools")
async def catalog_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Return the tool catalogue with schemas."""
    definitions = tools.get_definitions()
    return {
        "count": len(definitions),
        "tools": [
            {
                "name": d.name,
                "description": d.description,
                "parameters_schema": d.parameters_schema,
            }
            for d in definitions
        ],
        "harness_policies": ["CodePolicy", "DataPolicy", "PIIPolicy"],
        "mcp_mounted": _mcp_mounted,
    }


# ---------------------------------------------------------------------------
# MCP server (optional — requires pip install agentharnessapi[mcp])
# ---------------------------------------------------------------------------

_mcp_mounted = False

try:
    from agenticapi.mcp_tools import HarnessMCPServer

    HarnessMCPServer(app, path="/mcp/tools")
    _mcp_mounted = True
except ImportError:
    pass  # mcp package not installed — agent endpoints still work
