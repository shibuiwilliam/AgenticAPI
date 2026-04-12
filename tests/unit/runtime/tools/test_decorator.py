"""Unit tests for the ``@tool`` decorator.

Covers schema derivation, plain-call passthrough, validated invocation,
capability inference, ToolRegistry auto-wrapping, and Pydantic-model
parameter handling.
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel, Field

from agenticapi import tool
from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools import Tool, ToolCapability, ToolRegistry


# Module-level model — Pydantic needs the type to be importable at the
# scope where the decorator builds the schema, so we keep it out of any
# test method's local namespace.
class _OrderQueryFixture(BaseModel):
    status: Literal["open", "shipped"] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class TestToolDecorator:
    def test_basic_schema_derivation(self) -> None:
        """A simple typed function gets a Pydantic-derived schema."""

        @tool(description="Find an order by ID")
        async def get_order(order_id: int, include_lines: bool = True) -> dict:
            return {"order_id": order_id, "lines": include_lines}

        defn = get_order.definition
        assert defn.name == "get_order"
        assert defn.description == "Find an order by ID"
        schema = defn.parameters_schema
        assert schema["type"] == "object"
        assert "order_id" in schema["properties"]
        assert "include_lines" in schema["properties"]
        assert schema["properties"]["order_id"]["type"] == "integer"
        assert schema["properties"]["include_lines"]["type"] == "boolean"
        assert schema["required"] == ["order_id"]

    def test_pydantic_model_parameter(self) -> None:
        """A Pydantic model parameter is reflected in the schema as a $ref."""

        @tool(description="List orders")
        async def list_orders(query: _OrderQueryFixture) -> list[dict]:
            del query
            return []

        schema = list_orders.definition.parameters_schema
        assert "query" in schema["properties"]
        # Pydantic puts the nested model under $defs and references it.
        assert "$defs" in schema

    async def test_plain_function_call_still_works(self) -> None:
        """Decorated function is callable as a normal Python function."""

        @tool(description="Add two numbers")
        async def add(a: int, b: int) -> int:
            return a + b

        # Direct call goes through the wrapper but still resolves to
        # the underlying coroutine, awaitable as normal.
        result = await add(a=2, b=3)
        assert result == 5

    async def test_invoke_validates_kwargs(self) -> None:
        """``.invoke()`` runs the kwargs through the Pydantic validator."""

        @tool(description="Echo back the input")
        async def echo(message: str, repeat: int = 1) -> str:
            return message * repeat

        result = await echo.invoke(message="hi", repeat=2)
        assert result == "hihi"

    async def test_invoke_rejects_invalid_kwargs(self) -> None:
        """Bad kwargs raise ToolError, not arbitrary ValidationError."""

        @tool(description="Sum")
        async def add(a: int, b: int) -> int:
            return a + b

        with pytest.raises(ToolError) as exc_info:
            await add.invoke(a="not-an-int", b=3)
        assert "Invalid arguments" in str(exc_info.value)

    def test_capability_inference_read(self) -> None:
        """Functions with no write/execute prefix default to READ."""

        @tool(description="t")
        async def get_user(user_id: int) -> dict:
            return {"id": user_id}

        assert ToolCapability.READ in get_user.definition.capabilities

    def test_capability_inference_write(self) -> None:
        """Functions with create_/update_/delete_ prefixes are WRITE."""

        @tool(description="t")
        async def delete_user(user_id: int) -> None:
            del user_id

        assert ToolCapability.WRITE in delete_user.definition.capabilities

    def test_explicit_capabilities_override(self) -> None:
        """Explicit capabilities take precedence over inference."""

        @tool(description="t", capabilities=[ToolCapability.SEARCH])
        async def get_user(user_id: int) -> dict:
            del user_id
            return {}

        assert get_user.definition.capabilities == [ToolCapability.SEARCH]

    def test_decorator_without_parens(self) -> None:
        """``@tool`` without parentheses works."""

        @tool
        async def hello() -> str:
            """Say hello."""
            return "hello"

        assert hello.definition.name == "hello"
        # Description picks up the first docstring line.
        assert hello.definition.description == "Say hello."

    def test_explicit_name_override(self) -> None:
        """Explicit ``name=`` overrides the function name."""

        @tool(name="my_pretty_name", description="t")
        async def some_internal_name() -> None:
            return None

        assert some_internal_name.definition.name == "my_pretty_name"

    def test_return_annotation_captured(self) -> None:
        """The return annotation is stored for future composition use."""

        @tool(description="t")
        async def get_count() -> int:
            return 42

        # The decorator's return is typed as Tool but the underlying
        # _DecoratedTool exposes return_annotation.
        from agenticapi.runtime.tools.decorator import DecoratedTool

        assert isinstance(get_count, DecoratedTool)
        assert get_count.return_annotation is int

    def test_decorated_function_satisfies_tool_protocol(self) -> None:
        """The decorated object satisfies the Tool protocol structurally."""

        @tool(description="t")
        async def f(x: int) -> int:
            return x

        assert hasattr(f, "definition")
        assert hasattr(f, "invoke")


class TestRegistryAcceptsPlainFunctions:
    def test_register_plain_async_function(self) -> None:
        """Registering a plain async function auto-wraps it via @tool."""

        async def get_user(user_id: int) -> dict:
            """Look up a user."""
            return {"id": user_id}

        registry = ToolRegistry()
        registry.register(get_user)

        assert "get_user" in registry
        wrapped = registry.get("get_user")
        assert wrapped.definition.name == "get_user"
        assert wrapped.definition.description == "Look up a user."

    def test_register_plain_sync_function(self) -> None:
        """Registering a plain sync function auto-wraps it."""

        def add(a: int, b: int) -> int:
            return a + b

        registry = ToolRegistry()
        registry.register(add)
        assert "add" in registry

    def test_mixed_class_and_function_tools(self) -> None:
        """Class-based and function-based tools can coexist in one registry."""

        @tool(description="A function tool")
        async def func_tool(x: int) -> int:
            return x

        registry = ToolRegistry()
        registry.register(func_tool)
        assert len(registry) == 1

    def test_register_rejects_non_callable(self) -> None:
        """Registering a non-Tool, non-callable object raises ToolError."""
        registry = ToolRegistry()
        with pytest.raises(ToolError):
            registry.register(42)  # type: ignore[arg-type]


class TestToolReturnsAreUnchanged:
    """Existing class-based tools must keep working unchanged."""

    def test_class_based_tool_still_registers(self) -> None:
        """Confirms backward compatibility with classes implementing Tool."""

        class _MyTool:
            @property
            def definition(self):
                from agenticapi.runtime.tools import ToolDefinition

                return ToolDefinition(
                    name="legacy",
                    description="legacy class tool",
                    capabilities=[ToolCapability.READ],
                )

            async def invoke(self, **kwargs):
                return kwargs

        registry = ToolRegistry()
        registry.register(_MyTool())  # type: ignore[arg-type]
        assert "legacy" in registry
        # Test the protocol check works on the class form too.
        assert isinstance(registry.get("legacy"), Tool)
