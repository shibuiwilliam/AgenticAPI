"""HTTP client tool for agent API calls.

Provides a tool that wraps httpx for making HTTP requests,
with allowed_hosts enforcement for security.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import structlog

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition

logger = structlog.get_logger(__name__)


class HttpClientTool:
    """A tool for making HTTP requests.

    Wraps httpx.AsyncClient with optional host allowlisting.
    Supports GET, POST, PUT, PATCH, DELETE methods.

    Example:
        tool = HttpClientTool(allowed_hosts=["api.example.com"])
        result = await tool.invoke(method="GET", url="https://api.example.com/data")
    """

    _ALLOWED_METHODS: frozenset[str] = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

    def __init__(
        self,
        *,
        name: str = "http_client",
        description: str = "Make HTTP requests to external APIs",
        allowed_hosts: list[str] | None = None,
        timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize the HTTP client tool.

        Args:
            name: The name for this tool instance.
            description: Human-readable description.
            allowed_hosts: If set, only requests to these hosts are permitted.
            timeout: Default request timeout in seconds.
            default_headers: Default headers to include in every request.
        """
        self._name = name
        self._description = description
        self._allowed_hosts = set(allowed_hosts) if allowed_hosts else None
        self._timeout = timeout
        self._default_headers = default_headers or {}

    @property
    def definition(self) -> ToolDefinition:
        """Return the tool's metadata definition."""
        return ToolDefinition(
            name=self._name,
            description=self._description,
            capabilities=[ToolCapability.READ, ToolCapability.EXECUTE],
            parameters_schema={
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "HTTP method (GET, POST, PUT, PATCH, DELETE)",
                    },
                    "url": {"type": "string", "description": "The URL to request"},
                    "headers": {
                        "type": "object",
                        "description": "Additional HTTP headers",
                        "default": None,
                    },
                    "body": {
                        "description": "Request body (for POST/PUT/PATCH)",
                        "default": None,
                    },
                },
                "required": ["method", "url"],
            },
        )

    async def invoke(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: Any = None,
    ) -> dict[str, Any]:
        """Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, etc.).
            url: The URL to request.
            headers: Optional additional headers.
            body: Optional request body (JSON-serializable).

        Returns:
            Dict with status, headers, and body.

        Raises:
            ToolError: If the host is not allowed, method is invalid,
                       or the request fails.
        """
        method_upper = method.upper()
        if method_upper not in self._ALLOWED_METHODS:
            raise ToolError(f"HTTP method '{method}' is not allowed")

        # Validate host
        parsed = urlparse(url)
        if not parsed.hostname:
            raise ToolError(f"Invalid URL: {url}")

        if self._allowed_hosts is not None and parsed.hostname not in self._allowed_hosts:
            raise ToolError(
                f"Host '{parsed.hostname}' is not in the allowed hosts list. Allowed: {sorted(self._allowed_hosts)}"
            )

        logger.info(
            "http_client_tool_invoke",
            tool_name=self._name,
            method=method_upper,
            url=url[:200],
        )

        try:
            import httpx

            merged_headers = {**self._default_headers, **(headers or {})}
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method=method_upper,
                    url=url,
                    headers=merged_headers,
                    json=body if body is not None else None,
                )

            return {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
            }
        except ToolError:
            raise
        except Exception as exc:
            logger.error("http_client_tool_error", tool_name=self._name, error=str(exc))
            raise ToolError(f"HTTP request failed: {exc}") from exc
