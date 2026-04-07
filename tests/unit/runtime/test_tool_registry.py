"""Tests for ToolRegistry."""

from __future__ import annotations

from typing import Any

import pytest

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition
from agenticapi.runtime.tools.registry import ToolRegistry


class _FakeTool:
    """A simple fake tool for testing."""

    def __init__(self, name: str, capabilities: list[ToolCapability] | None = None) -> None:
        self._definition = ToolDefinition(
            name=name,
            description=f"Fake tool: {name}",
            capabilities=capabilities or [ToolCapability.READ],
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def invoke(self, **kwargs: Any) -> Any:
        return {"tool": self._definition.name, **kwargs}


class TestToolRegistryRegisterAndGet:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = _FakeTool("database")
        registry.register(tool)
        retrieved = registry.get("database")
        assert retrieved.definition.name == "database"

    def test_get_unknown_raises(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(ToolError, match="not found"):
            registry.get("nonexistent")

    def test_duplicate_name_raises(self) -> None:
        registry = ToolRegistry()
        registry.register(_FakeTool("database"))
        with pytest.raises(ToolError, match="already registered"):
            registry.register(_FakeTool("database"))


class TestToolRegistryListTools:
    def test_list_tools_empty(self) -> None:
        registry = ToolRegistry()
        assert registry.list_tools() == []

    def test_list_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(_FakeTool("db"))
        registry.register(_FakeTool("cache"))
        definitions = registry.list_tools()
        names = [d.name for d in definitions]
        assert "db" in names
        assert "cache" in names
        assert len(definitions) == 2


class TestToolRegistryInitWithTools:
    def test_init_with_list(self) -> None:
        tools = [_FakeTool("a"), _FakeTool("b")]
        registry = ToolRegistry(tools=tools)
        assert len(registry) == 2
        assert "a" in registry
        assert "b" in registry


class TestToolRegistryContains:
    def test_contains(self) -> None:
        registry = ToolRegistry()
        registry.register(_FakeTool("test"))
        assert "test" in registry
        assert "missing" not in registry


class TestToolRegistryLen:
    def test_len(self) -> None:
        registry = ToolRegistry()
        assert len(registry) == 0
        registry.register(_FakeTool("one"))
        assert len(registry) == 1


class TestToolRegistryGetDefinitions:
    def test_get_definitions_same_as_list_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(_FakeTool("x"))
        assert registry.get_definitions() == registry.list_tools()
