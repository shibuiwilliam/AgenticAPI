"""Compatibility layer for REST and FastAPI interop.

Re-exports key functions for convenient access.
"""

from __future__ import annotations

from agenticapi.interface.compat.fastapi import mount_fastapi, mount_in_agenticapi
from agenticapi.interface.compat.rest import RESTCompat, expose_as_rest

__all__ = [
    "RESTCompat",
    "expose_as_rest",
    "mount_fastapi",
    "mount_in_agenticapi",
]
