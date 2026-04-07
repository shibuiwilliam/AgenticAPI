"""Tool protocol and base definitions.

Defines the Tool protocol for pluggable tool implementations and
the ToolDefinition data class describing a tool's capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ToolCapability(StrEnum):
    """Capabilities that a tool can provide.

    Used for policy evaluation to determine what operations
    a tool is permitted to perform.
    """

    READ = "read"
    WRITE = "write"
    AGGREGATE = "aggregate"
    SEARCH = "search"
    EXECUTE = "execute"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Metadata describing a tool's interface and capabilities.

    Attributes:
        name: Unique identifier for the tool.
        description: Human-readable description of what the tool does.
        capabilities: List of capabilities this tool provides.
        parameters_schema: JSON Schema describing the tool's parameters.
    """

    name: str
    description: str
    capabilities: list[ToolCapability]
    parameters_schema: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """Protocol for tool implementations.

    Tools are pluggable components that agents can use to interact
    with external systems (databases, APIs, caches, etc.).

    Using Protocol so that third-party tool implementations can
    satisfy this interface without depending on AgenticAPI.
    """

    @property
    def definition(self) -> ToolDefinition:
        """Return the tool's metadata definition."""
        ...

    async def invoke(self, **kwargs: Any) -> Any:
        """Invoke the tool with the given keyword arguments.

        Args:
            **kwargs: Tool-specific parameters.

        Returns:
            The tool's result (type depends on the tool).
        """
        ...
