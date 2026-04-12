"""Tool abstractions and implementations.

Provides the Tool protocol, ToolRegistry for management,
and concrete tool implementations.
"""

from __future__ import annotations

from agenticapi.runtime.tools.base import Tool, ToolCapability, ToolDefinition
from agenticapi.runtime.tools.cache import CacheTool
from agenticapi.runtime.tools.database import DatabaseTool
from agenticapi.runtime.tools.decorator import DecoratedTool, tool
from agenticapi.runtime.tools.http_client import HttpClientTool
from agenticapi.runtime.tools.queue import QueueTool
from agenticapi.runtime.tools.registry import ToolRegistry

__all__ = [
    "CacheTool",
    "DatabaseTool",
    "DecoratedTool",
    "HttpClientTool",
    "QueueTool",
    "Tool",
    "ToolCapability",
    "ToolDefinition",
    "ToolRegistry",
    "tool",
]
