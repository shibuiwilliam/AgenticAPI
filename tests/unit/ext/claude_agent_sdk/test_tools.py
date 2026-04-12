"""Tests for the AgenticAPI → SDK MCP tool bridge."""

from __future__ import annotations

from typing import Any

import pytest

from agenticapi.ext.claude_agent_sdk.tools import (
    build_sdk_mcp_server_from_registry,
    sdk_tool_from_agenticapi_tool,
)
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition
from agenticapi.runtime.tools.registry import ToolRegistry


class _EchoTool:
    def __init__(self, name: str = "echo") -> None:
        self._name = name

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description="Echo arguments back as JSON",
            capabilities=[ToolCapability.READ],
        )

    async def invoke(self, **kwargs: Any) -> Any:
        return {"echoed": kwargs}


class _RaisingTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="boom",
            description="Always raises",
            capabilities=[ToolCapability.READ],
        )

    async def invoke(self, **kwargs: Any) -> Any:
        del kwargs
        raise RuntimeError("kaboom")


async def test_sdk_tool_wraps_agenticapi_tool() -> None:
    sdk_tool = sdk_tool_from_agenticapi_tool(_EchoTool())
    # The handler is the inner async function the decorator captured.
    result = await sdk_tool.handler({"query": "hi"})
    assert "content" in result
    assert "hi" in result["content"][0]["text"]


async def test_sdk_tool_handles_exceptions_gracefully() -> None:
    sdk_tool = sdk_tool_from_agenticapi_tool(_RaisingTool())
    result = await sdk_tool.handler({})
    assert result.get("isError") is True
    assert "kaboom" in result["content"][0]["text"]


def test_build_sdk_mcp_server_from_registry() -> None:
    registry = ToolRegistry()
    registry.register(_EchoTool("echo1"))
    registry.register(_EchoTool("echo2"))

    server, allowed_patterns = build_sdk_mcp_server_from_registry(registry, name="agenticapi")

    assert server.name == "agenticapi"
    assert len(server.tools) == 2
    assert {t.name for t in server.tools} == {"echo1", "echo2"}
    assert set(allowed_patterns) == {"mcp__agenticapi__echo1", "mcp__agenticapi__echo2"}


@pytest.mark.parametrize(
    "schema,expected_keys",
    [
        ({}, {"type", "properties"}),
        ({"type": "object", "properties": {"x": {"type": "integer"}}}, {"type", "properties"}),
        ({"properties": {"x": {"type": "integer"}}}, {"type", "properties"}),
    ],
)
def test_sdk_tool_input_schema_normalisation(schema: dict[str, Any], expected_keys: set[str]) -> None:
    class _T:
        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="t",
                description="t",
                capabilities=[ToolCapability.READ],
                parameters_schema=schema,
            )

        async def invoke(self, **_: Any) -> Any:
            return {}

    sdk_tool = sdk_tool_from_agenticapi_tool(_T())
    assert expected_keys.issubset(set(sdk_tool.input_schema.keys()))
    assert sdk_tool.input_schema["type"] == "object"
