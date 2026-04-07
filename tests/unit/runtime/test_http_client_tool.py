"""Tests for HttpClientTool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.http_client import HttpClientTool


class TestHttpClientToolDefinition:
    def test_definition_has_correct_name(self) -> None:
        tool = HttpClientTool(name="api")
        assert tool.definition.name == "api"

    def test_definition_has_execute_capability(self) -> None:
        tool = HttpClientTool()
        caps = tool.definition.capabilities
        assert "read" in [c.value for c in caps]
        assert "execute" in [c.value for c in caps]

    def test_definition_has_parameters_schema(self) -> None:
        tool = HttpClientTool()
        schema = tool.definition.parameters_schema
        assert "method" in schema["properties"]
        assert "url" in schema["properties"]


class TestHttpClientToolValidation:
    async def test_rejects_invalid_method(self) -> None:
        tool = HttpClientTool()
        with pytest.raises(ToolError, match="not allowed"):
            await tool.invoke(method="INVALID", url="https://example.com")

    async def test_rejects_invalid_url(self) -> None:
        tool = HttpClientTool()
        with pytest.raises(ToolError, match="Invalid URL"):
            await tool.invoke(method="GET", url="not-a-url")

    async def test_rejects_disallowed_host(self) -> None:
        tool = HttpClientTool(allowed_hosts=["api.example.com"])
        with pytest.raises(ToolError, match="not in the allowed hosts"):
            await tool.invoke(method="GET", url="https://evil.com/data")

    async def test_allows_permitted_host(self) -> None:
        tool = HttpClientTool(allowed_hosts=["nonexistent.invalid"])
        # Should pass host validation (but fail at network)
        with pytest.raises(ToolError, match="HTTP request failed"):
            await tool.invoke(method="GET", url="https://nonexistent.invalid/test")

    async def test_no_host_restriction_when_none(self) -> None:
        tool = HttpClientTool(allowed_hosts=None)
        # Should pass host validation (but fail at network)
        with pytest.raises(ToolError, match="HTTP request failed"):
            await tool.invoke(method="GET", url="https://nonexistent.invalid/test")


class TestHttpClientToolInvoke:
    def _make_mock_httpx(self, *, status_code: int = 200, text: str = "", headers: dict | None = None) -> MagicMock:
        """Create a mock httpx module with AsyncClient."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.headers = headers or {}
        mock_response.text = text

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        return mock_httpx, mock_client

    async def test_successful_get_returns_response_dict(self) -> None:
        mock_httpx, _mock_client = self._make_mock_httpx(
            status_code=200,
            text='{"data": "value"}',
            headers={"content-type": "application/json"},
        )

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            tool = HttpClientTool()
            result = await tool.invoke(method="GET", url="https://api.example.com/data")

        assert result["status"] == 200
        assert result["body"] == '{"data": "value"}'

    async def test_merges_default_headers(self) -> None:
        mock_httpx, mock_client = self._make_mock_httpx()

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            tool = HttpClientTool(default_headers={"Authorization": "Bearer token"})
            await tool.invoke(
                method="GET",
                url="https://api.example.com/data",
                headers={"X-Custom": "value"},
            )

        call_kwargs = mock_client.request.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer token"
        assert call_kwargs["headers"]["X-Custom"] == "value"

    async def test_post_with_json_body(self) -> None:
        mock_httpx, mock_client = self._make_mock_httpx(status_code=201, text='{"id": 1}')

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            tool = HttpClientTool()
            result = await tool.invoke(
                method="POST",
                url="https://api.example.com/items",
                body={"name": "test"},
            )

        assert result["status"] == 201
        call_kwargs = mock_client.request.call_args[1]
        assert call_kwargs["json"] == {"name": "test"}
