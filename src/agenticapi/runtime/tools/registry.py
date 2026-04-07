"""Tool registry for managing and looking up tools.

Provides centralized registration and lookup of tools available
to agents during code generation and execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from agenticapi.exceptions import ToolError

if TYPE_CHECKING:
    from agenticapi.runtime.tools.base import Tool, ToolDefinition

logger = structlog.get_logger(__name__)


class ToolRegistry:
    """Registry for managing available tools.

    Manages tool registration, lookup by name, and provides
    tool definitions for code generation prompts.

    Example:
        registry = ToolRegistry()
        registry.register(database_tool)
        tool = registry.get("database")
        definitions = registry.get_definitions()
    """

    def __init__(self, tools: list[Tool] | None = None) -> None:
        """Initialize the registry with optional initial tools.

        Args:
            tools: Optional list of tools to register immediately.
        """
        self._tools: dict[str, Tool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        """Register a tool in the registry.

        Args:
            tool: The tool to register. Must have a unique name.

        Raises:
            ToolError: If a tool with the same name is already registered.
        """
        name = tool.definition.name
        if name in self._tools:
            raise ToolError(f"Tool '{name}' is already registered")
        self._tools[name] = tool
        logger.info("tool_registered", tool_name=name, capabilities=[c.value for c in tool.definition.capabilities])

    def get(self, name: str) -> Tool:
        """Look up a tool by name.

        Args:
            name: The name of the tool to retrieve.

        Returns:
            The registered tool.

        Raises:
            ToolError: If no tool with the given name is registered.
        """
        tool = self._tools.get(name)
        if tool is None:
            available = list(self._tools.keys())
            raise ToolError(f"Tool '{name}' not found. Available tools: {available}")
        return tool

    def list_tools(self) -> list[ToolDefinition]:
        """Return definitions for all registered tools.

        Returns:
            List of ToolDefinition objects for all registered tools.
        """
        return [tool.definition for tool in self._tools.values()]

    def get_definitions(self) -> list[ToolDefinition]:
        """Return definitions for all registered tools.

        Alias for list_tools() for API consistency.

        Returns:
            List of ToolDefinition objects for all registered tools.
        """
        return self.list_tools()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
