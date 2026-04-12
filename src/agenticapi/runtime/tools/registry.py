"""Tool registry for managing and looking up tools.

Provides centralized registration and lookup of tools available
to agents during code generation and execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import ToolError

if TYPE_CHECKING:
    from collections.abc import Callable

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

    def __init__(self, tools: list[Tool | Callable[..., Any]] | None = None) -> None:
        """Initialize the registry with optional initial tools.

        Args:
            tools: Optional list of tools to register immediately.
                Each entry may be either a :class:`Tool` instance or a
                plain function — plain functions are auto-wrapped via
                :func:`agenticapi.runtime.tools.tool` so you can mix
                both styles freely.
        """
        self._tools: dict[str, Tool] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool | Callable[..., Any]) -> None:
        """Register a tool in the registry.

        Args:
            tool: The tool to register. May be either a :class:`Tool`
                instance or a plain (sync or async) function. Plain
                functions are automatically wrapped via the
                :func:`agenticapi.runtime.tools.tool` decorator so the
                FastAPI-style ``register(my_func)`` shortcut works.

        Raises:
            ToolError: If a tool with the same name is already registered.
        """
        # Auto-wrap plain functions for the FastAPI-style ergonomic
        # ``registry.register(my_func)`` form. We detect "is this a
        # Tool already" by checking for the protocol's ``definition``
        # attribute, which is more reliable than ``isinstance(...)``
        # against a runtime-checkable Protocol.
        if not (hasattr(tool, "definition") and hasattr(tool, "invoke")):
            if not callable(tool):
                raise ToolError(f"Cannot register non-callable, non-Tool object: {tool!r}")
            from agenticapi.runtime.tools.decorator import tool as _tool_decorator

            tool = _tool_decorator(tool)

        # By this point ``tool`` definitely satisfies the protocol.
        name = tool.definition.name
        if name in self._tools:
            raise ToolError(f"Tool '{name}' is already registered")
        self._tools[name] = tool
        logger.info(
            "tool_registered",
            tool_name=name,
            capabilities=[c.value for c in tool.definition.capabilities],
        )

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
