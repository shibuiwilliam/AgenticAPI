"""Compatibility layer for REST, FastAPI, and MCP interop.

Re-exports key functions for convenient access.
"""

from __future__ import annotations

import contextlib

from agenticapi.interface.compat.fastapi import mount_fastapi, mount_in_agenticapi
from agenticapi.interface.compat.rest import RESTCompat, expose_as_rest

__all__ = [
    "MCPCompat",
    "RESTCompat",
    "expose_as_mcp",
    "expose_as_rest",
    "mount_fastapi",
    "mount_in_agenticapi",
]

# MCP support is optional — only available when the 'mcp' package is installed.
with contextlib.suppress(ImportError):
    from agenticapi.interface.compat.mcp import MCPCompat, expose_as_mcp
