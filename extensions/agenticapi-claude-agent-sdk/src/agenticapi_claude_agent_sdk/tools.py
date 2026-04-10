"""Tool bridge: AgenticAPI ``Tool`` → Claude Agent SDK MCP tools.

The Claude Agent SDK exposes custom tools to the model through MCP
(Model Context Protocol) servers. SDK MCP servers can be in-process
(``create_sdk_mcp_server``) so we don't need to spawn a subprocess
or speak JSON-RPC: we just hand the SDK a list of decorated callables
and the model can call them directly.

This module converts each AgenticAPI :class:`agenticapi.runtime.tools.base.Tool`
into an SDK MCP tool, then bundles the result into a single
``McpSdkServerConfig`` named after the AgenticAPI app.

The mapping is intentionally narrow: AgenticAPI tools take ``**kwargs``
and return JSON-serialisable values; SDK MCP tools take a single ``args``
dict and return ``{"content": [{"type": "text", "text": ...}]}``. The
bridge handles the conversion both ways.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog
from agenticapi.exceptions import ToolError

from agenticapi_claude_agent_sdk._imports import load_sdk

if TYPE_CHECKING:
    from agenticapi.runtime.tools.base import Tool, ToolDefinition
    from agenticapi.runtime.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


def _coerce_to_text(value: Any) -> str:
    """Coerce an arbitrary tool result into a text string.

    Strings pass through; everything else is JSON-encoded with a
    fallback to ``repr()`` for non-serialisable objects.
    """
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def _build_input_schema(definition: ToolDefinition) -> dict[str, Any]:
    """Build a JSON Schema dict for an AgenticAPI tool definition.

    The Claude Agent SDK accepts either a Python type or a JSON Schema
    dict. AgenticAPI tools carry an optional ``parameters_schema`` on
    their definition. When it's empty (most common case for the simple
    ``Tool`` protocol), we fall back to a permissive schema that accepts
    a single optional ``query`` string parameter — this matches the
    convention used internally by AgenticAPI's process sandbox.
    """
    schema = dict(definition.parameters_schema or {})
    if not schema:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-form query passed to the tool's invoke() method.",
                },
            },
            "additionalProperties": True,
        }
    if "type" not in schema:
        schema["type"] = "object"
    return schema


def sdk_tool_from_agenticapi_tool(tool: Tool) -> Any:
    """Convert a single AgenticAPI tool into an SDK MCP tool.

    The returned object is the value produced by the SDK's ``@tool``
    decorator (a ``SdkMcpTool``). It's intentionally typed as ``Any``
    because the SDK isn't a hard dependency of this module's import.

    Args:
        tool: An object satisfying the AgenticAPI :class:`Tool` protocol.

    Returns:
        An ``SdkMcpTool`` ready to be passed to ``create_sdk_mcp_server``.

    Raises:
        ClaudeAgentSDKNotInstalledError: If ``claude_agent_sdk`` is not
            installed.
    """
    sdk = load_sdk()
    definition = tool.definition
    name = definition.name
    description = definition.description or f"AgenticAPI tool: {name}"
    input_schema = _build_input_schema(definition)

    async def _invoke(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await tool.invoke(**args)
            text = _coerce_to_text(result)
            return {"content": [{"type": "text", "text": text}]}
        except ToolError as exc:
            logger.warning("sdk_tool_invoke_tool_error", tool=name, error=str(exc))
            return {
                "content": [{"type": "text", "text": f"ToolError: {exc}"}],
                "isError": True,
            }
        except Exception as exc:
            logger.error("sdk_tool_invoke_unexpected", tool=name, error=str(exc))
            return {
                "content": [{"type": "text", "text": f"Unexpected error: {exc}"}],
                "isError": True,
            }

    decorator = sdk.tool(name, description, input_schema)
    return decorator(_invoke)


def build_sdk_mcp_server_from_registry(
    registry: ToolRegistry,
    *,
    name: str = "agenticapi",
    version: str = "1.0.0",
) -> tuple[Any, list[str]]:
    """Build an in-process SDK MCP server from an AgenticAPI tool registry.

    Args:
        registry: The AgenticAPI :class:`ToolRegistry` to expose.
        name: Logical name of the MCP server. Tools become reachable
            from the model as ``mcp__<name>__<tool_name>``.
        version: SemVer string for the MCP server.

    Returns:
        A tuple of (``McpSdkServerConfig``, ``allowed_tool_patterns``)
        where the second item is a list of fully-qualified tool name
        patterns (e.g. ``["mcp__agenticapi__db", "mcp__agenticapi__cache"]``)
        suitable for passing to ``ClaudeAgentOptions.allowed_tools``.

    Raises:
        ClaudeAgentSDKNotInstalledError: If ``claude_agent_sdk`` is not
            installed.
    """
    sdk = load_sdk()
    sdk_tools: list[Any] = []
    allowed_patterns: list[str] = []
    for definition in registry.get_definitions():
        tool = registry.get(definition.name)
        sdk_tools.append(sdk_tool_from_agenticapi_tool(tool))
        allowed_patterns.append(f"mcp__{name}__{definition.name}")

    server = sdk.create_sdk_mcp_server(name=name, version=version, tools=sdk_tools)
    logger.info(
        "sdk_mcp_server_built",
        server_name=name,
        tool_count=len(sdk_tools),
        tools=[d.name for d in registry.get_definitions()],
    )
    return server, allowed_patterns
