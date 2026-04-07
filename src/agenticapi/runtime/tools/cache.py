"""Cache tool for agent key-value storage.

Provides an in-memory cache with TTL support for agent operations.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition

logger = structlog.get_logger(__name__)


class CacheTool:
    """An in-memory cache tool with TTL support.

    Provides get, set, delete, and exists operations on a
    key-value store with per-entry expiration.

    Example:
        tool = CacheTool(default_ttl_seconds=300)
        await tool.invoke(action="set", key="user:1", value={"name": "Alice"})
        result = await tool.invoke(action="get", key="user:1")
    """

    _ALLOWED_ACTIONS: frozenset[str] = frozenset({"get", "set", "delete", "exists"})

    def __init__(
        self,
        *,
        name: str = "cache",
        description: str = "In-memory key-value cache with TTL",
        max_size: int = 1000,
        default_ttl_seconds: float = 300.0,
    ) -> None:
        """Initialize the cache tool.

        Args:
            name: The name for this tool instance.
            description: Human-readable description.
            max_size: Maximum number of entries before eviction.
            default_ttl_seconds: Default TTL for entries in seconds.
        """
        self._name = name
        self._description = description
        self._max_size = max_size
        self._default_ttl = default_ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)

    @property
    def definition(self) -> ToolDefinition:
        """Return the tool's metadata definition."""
        return ToolDefinition(
            name=self._name,
            description=self._description,
            capabilities=[ToolCapability.READ, ToolCapability.WRITE],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["get", "set", "delete", "exists"],
                        "description": "Cache operation to perform",
                    },
                    "key": {"type": "string", "description": "Cache key"},
                    "value": {"description": "Value to cache (for set)", "default": None},
                    "ttl": {
                        "type": "number",
                        "description": "TTL in seconds (for set)",
                        "default": None,
                    },
                },
                "required": ["action", "key"],
            },
        )

    async def invoke(
        self,
        *,
        action: str,
        key: str,
        value: Any = None,
        ttl: float | None = None,
    ) -> Any:
        """Perform a cache operation.

        Args:
            action: One of "get", "set", "delete", "exists".
            key: The cache key.
            value: The value to store (required for "set").
            ttl: TTL in seconds (defaults to default_ttl_seconds).

        Returns:
            The cached value for "get", True/False for "exists",
            None for "set" and "delete".

        Raises:
            ToolError: If the action is invalid.
        """
        if action not in self._ALLOWED_ACTIONS:
            raise ToolError(f"Invalid cache action '{action}'. Allowed: {sorted(self._ALLOWED_ACTIONS)}")

        logger.info("cache_tool_invoke", tool_name=self._name, action=action, key=key)

        if action == "get":
            return self._get(key)
        elif action == "set":
            self._set(key, value, ttl)
            return None
        elif action == "delete":
            self._delete(key)
            return None
        elif action == "exists":
            return self._exists(key)
        return None

    def _get(self, key: str) -> Any:
        """Get a value from the cache."""
        entry = self._store.get(key)
        if entry is None:
            return None

        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None

        return value

    def _set(self, key: str, value: Any, ttl: float | None) -> None:
        """Set a value in the cache."""
        # Evict oldest if at capacity
        if len(self._store) >= self._max_size and key not in self._store:
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]

        actual_ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.monotonic() + actual_ttl
        self._store[key] = (value, expires_at)

    def _delete(self, key: str) -> None:
        """Delete a key from the cache."""
        self._store.pop(key, None)

    def _exists(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        return self._get(key) is not None
