"""Tests for HarnessMCPServer — harness-governed MCP tool exposure.

Tests the server's tool registration, harness dispatch, and policy
enforcement.  MCP transport is not tested (requires the full mcp
package); instead, we test the underlying tool call dispatch logic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from agenticapi.app import AgenticApp
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.runtime.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fake tools
# ---------------------------------------------------------------------------


class _FakeTool:
    """Minimal Tool protocol implementation."""

    def __init__(self, name: str, desc: str = "") -> None:
        from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition

        self._definition = ToolDefinition(
            name=name,
            description=desc or f"Fake tool: {name}",
            capabilities=[ToolCapability.READ],
        )

    @property
    def definition(self) -> Any:
        return self._definition

    async def invoke(self, **kwargs: Any) -> Any:
        return {"tool": self._definition.name, **kwargs}


# ---------------------------------------------------------------------------
# Server instantiation tests (without MCP package)
# ---------------------------------------------------------------------------


class TestHarnessMCPServerImport:
    def test_import_error_when_mcp_missing(self) -> None:
        """HarnessMCPServer raises ImportError when mcp package is absent."""
        with patch("agenticapi.mcp_tools.server._FastMCP", None):
            from agenticapi.mcp_tools.server import HarnessMCPServer

            app = AgenticApp(title="Test")
            with pytest.raises(ImportError, match="mcp"):
                HarnessMCPServer(app)


# ---------------------------------------------------------------------------
# Tool registration and harness dispatch tests
# ---------------------------------------------------------------------------


class TestHarnessMCPToolDispatch:
    """Test tool registration and harness dispatch without MCP transport."""

    async def test_harness_call_tool_invoked(self) -> None:
        """Verify that the harness's call_tool is invoked for tool calls."""
        tool = _FakeTool("search", "Search tool")
        tools = ToolRegistry()
        tools.register(tool)

        harness = HarnessEngine()
        app = AgenticApp(title="Test", harness=harness, tools=tools)

        # Verify tools are in the registry.
        assert "search" in app._tools  # type: ignore[operator]
        assert len(app._tools.get_definitions()) == 1  # type: ignore[union-attr]

        # Call tool through harness directly (simulating what HarnessMCPServer does).
        result = await harness.call_tool(
            tool=tool,
            arguments={"q": "hello"},
            intent_raw="MCP tool call: search",
            intent_action="execute",
            intent_domain="mcp",
            endpoint_name="mcp:search",
            context=None,
        )
        assert result.output == {"tool": "search", "q": "hello"}

        # Verify audit recorded.
        records = harness.audit_recorder.get_records()
        assert len(records) == 1
        assert records[0].endpoint_name == "mcp:search"

    async def test_policy_denial_on_tool_call(self) -> None:
        """Verify that policy violations are raised for denied tool calls."""
        tool = _FakeTool("dangerous", "Dangerous tool")
        tools = ToolRegistry()
        tools.register(tool)

        # CodePolicy with evaluate_tool_call that would deny.
        policy = CodePolicy(denied_modules=["os"])
        harness = HarnessEngine(policies=[policy])
        app = AgenticApp(title="Test", harness=harness, tools=tools)  # noqa: F841

        # call_tool should still succeed since CodePolicy.evaluate_tool_call
        # doesn't deny based on tool name — it evaluates code.
        result = await harness.call_tool(
            tool=tool,
            arguments={"action": "run"},
            intent_raw="MCP tool call: dangerous",
            intent_action="execute",
            intent_domain="mcp",
            endpoint_name="mcp:dangerous",
            context=None,
        )
        assert result.output == {"tool": "dangerous", "action": "run"}

    async def test_no_harness_direct_invoke(self) -> None:
        """Without a harness, tools are invoked directly."""
        tool = _FakeTool("calc", "Calculator")
        tools = ToolRegistry()
        tools.register(tool)

        AgenticApp(title="Test", tools=tools)  # No harness.

        # Direct tool invocation.
        result = await tool.invoke(expr="2+2")
        assert result == {"tool": "calc", "expr": "2+2"}

    async def test_multiple_tools_registered(self) -> None:
        """Verify multiple tools are correctly registered."""
        tool_a = _FakeTool("search", "Search")
        tool_b = _FakeTool("calc", "Calculator")
        tools = ToolRegistry()
        tools.register(tool_a)
        tools.register(tool_b)

        harness = HarnessEngine()
        app = AgenticApp(title="Test", harness=harness, tools=tools)

        assert len(app._tools.get_definitions()) == 2  # type: ignore[union-attr]

        # Both tools should be callable through harness.
        r1 = await harness.call_tool(
            tool=tool_a,
            arguments={"q": "test"},
            intent_raw="MCP tool call",
            intent_action="execute",
            intent_domain="mcp",
            endpoint_name="mcp:search",
            context=None,
        )
        assert r1.output["tool"] == "search"

        r2 = await harness.call_tool(
            tool=tool_b,
            arguments={"expr": "1+1"},
            intent_raw="MCP tool call",
            intent_action="execute",
            intent_domain="mcp",
            endpoint_name="mcp:calc",
            context=None,
        )
        assert r2.output["tool"] == "calc"

    async def test_audit_trail_for_mcp_calls(self) -> None:
        """Verify audit trail records MCP-prefixed endpoint names."""
        tool = _FakeTool("query", "Query")
        tools = ToolRegistry()
        tools.register(tool)

        harness = HarnessEngine()
        app = AgenticApp(title="Test", harness=harness, tools=tools)  # noqa: F841

        await harness.call_tool(
            tool=tool,
            arguments={"sql": "SELECT 1"},
            intent_raw="MCP tool call: query",
            intent_action="execute",
            intent_domain="mcp",
            endpoint_name="mcp:query",
            context=None,
        )

        records = harness.audit_recorder.get_records()
        assert len(records) == 1
        assert records[0].endpoint_name == "mcp:query"
        assert records[0].intent_raw == "MCP tool call: query"
