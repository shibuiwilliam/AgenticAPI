"""Tests for CacheTool."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.cache import CacheTool


class TestCacheToolDefinition:
    def test_definition_has_correct_name(self) -> None:
        tool = CacheTool(name="my_cache")
        assert tool.definition.name == "my_cache"

    def test_definition_has_read_write_capabilities(self) -> None:
        tool = CacheTool()
        caps = [c.value for c in tool.definition.capabilities]
        assert "read" in caps
        assert "write" in caps


class TestCacheToolOperations:
    async def test_set_and_get(self) -> None:
        tool = CacheTool()
        await tool.invoke(action="set", key="k1", value="v1")
        result = await tool.invoke(action="get", key="k1")
        assert result == "v1"

    async def test_get_nonexistent_returns_none(self) -> None:
        tool = CacheTool()
        result = await tool.invoke(action="get", key="missing")
        assert result is None

    async def test_delete_removes_key(self) -> None:
        tool = CacheTool()
        await tool.invoke(action="set", key="k1", value="v1")
        await tool.invoke(action="delete", key="k1")
        result = await tool.invoke(action="get", key="k1")
        assert result is None

    async def test_exists_true_for_set_key(self) -> None:
        tool = CacheTool()
        await tool.invoke(action="set", key="k1", value="v1")
        result = await tool.invoke(action="exists", key="k1")
        assert result is True

    async def test_exists_false_for_missing_key(self) -> None:
        tool = CacheTool()
        result = await tool.invoke(action="exists", key="missing")
        assert result is False

    async def test_invalid_action_raises(self) -> None:
        tool = CacheTool()
        with pytest.raises(ToolError, match="Invalid cache action"):
            await tool.invoke(action="invalid", key="k1")

    async def test_max_size_eviction(self) -> None:
        tool = CacheTool(max_size=2)
        await tool.invoke(action="set", key="k1", value="v1")
        await tool.invoke(action="set", key="k2", value="v2")
        await tool.invoke(action="set", key="k3", value="v3")
        # k1 should be evicted (oldest)
        assert await tool.invoke(action="get", key="k1") is None
        assert await tool.invoke(action="get", key="k3") == "v3"

    async def test_stores_complex_values(self) -> None:
        tool = CacheTool()
        data = {"items": [1, 2, 3], "total": 42}
        await tool.invoke(action="set", key="data", value=data)
        result = await tool.invoke(action="get", key="data")
        assert result == data

    async def test_custom_ttl_per_entry(self) -> None:
        """Entries can have custom TTL overriding the default."""
        tool = CacheTool(default_ttl_seconds=3600)
        # Set with very short custom TTL
        await tool.invoke(action="set", key="short", value="val", ttl=0.01)
        # Immediately should still exist
        result = await tool.invoke(action="get", key="short")
        assert result == "val"

    async def test_update_existing_key(self) -> None:
        tool = CacheTool()
        await tool.invoke(action="set", key="k1", value="v1")
        await tool.invoke(action="set", key="k1", value="v2")
        result = await tool.invoke(action="get", key="k1")
        assert result == "v2"
