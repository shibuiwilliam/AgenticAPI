"""Database tool for agent query execution.

Provides a tool that wraps an async callable for executing database
queries, with support for read-only mode enforcement.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition

logger = structlog.get_logger(__name__)

# Type alias for the async database execution function
type AsyncExecuteFn = Callable[..., Coroutine[Any, Any, Any]]


class DatabaseTool:
    """A tool that executes database queries via an async callable.

    Wraps a user-provided async function for executing queries,
    enforcing read-only mode when configured.

    Example:
        async def execute_query(query: str, params: dict | None = None):
            return await db.fetch_all(query, params or {})

        tool = DatabaseTool(execute_fn=execute_query, read_only=True)
        result = await tool.invoke(query="SELECT COUNT(*) FROM orders")
    """

    # SQL keywords that indicate write operations
    _WRITE_KEYWORDS: frozenset[str] = frozenset(
        {
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "CREATE",
            "ALTER",
            "TRUNCATE",
            "REPLACE",
            "MERGE",
            "UPSERT",
        }
    )

    def __init__(
        self,
        *,
        name: str = "database",
        description: str = "Execute SQL queries against a database",
        execute_fn: AsyncExecuteFn | None = None,
        read_only: bool = True,
    ) -> None:
        """Initialize the database tool.

        Args:
            name: The name for this tool instance.
            description: Human-readable description.
            execute_fn: Async callable that executes queries.
                        Signature: async (query: str, params: dict | None) -> Any
            read_only: If True, reject write operations.
        """
        self._name = name
        self._description = description
        self._execute_fn = execute_fn
        self._read_only = read_only

    @property
    def definition(self) -> ToolDefinition:
        """Return the tool's metadata definition."""
        capabilities = [ToolCapability.READ, ToolCapability.AGGREGATE, ToolCapability.SEARCH]
        if not self._read_only:
            capabilities.append(ToolCapability.WRITE)

        return ToolDefinition(
            name=self._name,
            description=self._description,
            capabilities=capabilities,
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL query to execute"},
                    "params": {
                        "type": "object",
                        "description": "Query parameters for parameterized queries",
                        "default": None,
                    },
                },
                "required": ["query"],
            },
        )

    async def invoke(self, *, query: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a database query.

        Args:
            query: The SQL query string to execute.
            params: Optional parameters for parameterized queries.

        Returns:
            The query result from the execute function.

        Raises:
            ToolError: If the tool has no execute function configured,
                       or if a write operation is attempted in read-only mode.
        """
        if self._execute_fn is None:
            raise ToolError(f"DatabaseTool '{self._name}' has no execute function configured")

        if self._read_only and self._is_write_query(query):
            raise ToolError(
                f"DatabaseTool '{self._name}' is read-only. Write operations are not permitted. Query: {query[:100]}"
            )

        logger.info(
            "database_tool_invoke",
            tool_name=self._name,
            query_preview=query[:100],
            read_only=self._read_only,
        )

        try:
            return await self._execute_fn(query, params)
        except ToolError:
            raise
        except Exception as exc:
            logger.error("database_tool_error", tool_name=self._name, error=str(exc))
            raise ToolError(f"Database query execution failed: {exc}") from exc

    @classmethod
    def _is_write_query(cls, query: str) -> bool:
        """Check if a query is a write operation.

        Strips SQL comments before checking to prevent bypasses like:
            "-- comment\\nDELETE FROM users"

        Args:
            query: The SQL query to check.

        Returns:
            True if the query appears to be a write operation.
        """
        # Remove line comments (-- ...) and block comments (/* ... */)
        cleaned = re.sub(r"--[^\n]*", "", query)
        cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
        stripped = cleaned.strip().upper()
        return any(stripped.startswith(keyword) for keyword in cls._WRITE_KEYWORDS)
