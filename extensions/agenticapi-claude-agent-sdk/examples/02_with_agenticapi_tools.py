"""Expose AgenticAPI tools to Claude through the SDK's MCP bridge.

Prerequisites:
    pip install agentharnessapi agentharnessapi-claude-agent-sdk
    export ANTHROPIC_API_KEY=sk-...

Run:
    uvicorn examples.02_with_agenticapi_tools:app --reload

The runner registers an in-process MCP server containing the
products tool, so the model can call it as
``mcp__agenticapi__products`` during the agentic loop. AgenticAPI
policies (denied modules etc.) are bridged into Claude's permission
system.
"""

from __future__ import annotations

from typing import Any, ClassVar

from agenticapi import AgenticApp, CodePolicy
from agenticapi.ext.claude_agent_sdk import ClaudeAgentRunner
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition
from agenticapi.runtime.tools.registry import ToolRegistry


class ProductsTool:
    """Read-only access to a tiny in-memory product catalogue."""

    _DATA: ClassVar[list[dict[str, Any]]] = [
        {"id": 1, "name": "Widget", "price": 9.99},
        {"id": 2, "name": "Gadget", "price": 14.50},
        {"id": 3, "name": "Doohickey", "price": 3.25},
    ]

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="products",
            description="List or filter products in the catalogue",
            capabilities=[ToolCapability.READ],
        )

    async def invoke(self, **kwargs: Any) -> Any:
        query = str(kwargs.get("query", "")).lower()
        if not query or query == "*":
            return self._DATA
        return [p for p in self._DATA if query in p["name"].lower()]


registry = ToolRegistry()
registry.register(ProductsTool())

runner = ClaudeAgentRunner(
    system_prompt=(
        "You are an e-commerce assistant. "
        "When the user asks about products, call the `products` tool. "
        "Reply concisely with the data you found."
    ),
    tool_registry=registry,
    policies=[CodePolicy(denied_modules=["os", "subprocess", "sys"])],
    permission_mode="default",
    deny_unknown_tools=True,  # production-style strict mode
    max_turns=4,
)

app = AgenticApp(title="claude-agent-sdk demo — products")


@app.agent_endpoint(name="catalog", autonomy_level="manual")
async def catalog(intent, context):  # type: ignore[no-untyped-def]
    return await runner.run(intent=intent, context=context)
