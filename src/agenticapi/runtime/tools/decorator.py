"""``@tool`` decorator for declaring AgenticAPI tools as plain functions.

The Phase 1 ``Tool`` protocol required users to write a class with a
``definition`` property and a hand-written ``parameters_schema`` dict.
That's a lot of boilerplate for what should be the agent equivalent of
``@app.get`` — *write a function with type hints, get a tool*.

This decorator closes that gap. Given a plain ``async def`` (or sync
``def``) function with type hints, it returns an object that:

* Satisfies the existing :class:`Tool` protocol unchanged.
* Carries a JSON Schema in ``definition.parameters_schema`` derived
  from the function's parameters via Pydantic's
  :class:`pydantic.TypeAdapter` — no manual schema authoring.
* Captures the function's return annotation (when present) in a new
  ``return_schema`` attribute so future Phase E tasks can support
  typed tool composition.
* Validates kwargs at call time via the same Pydantic adapter so
  bad LLM tool-call payloads fail fast with a clear ``ValidationError``.
* Forwards plain Python calls (``my_tool(...)``) to the underlying
  function so users keep using their tool as a normal function in
  unit tests.

Example:
    from agenticapi import tool

    @tool(description="Find an order by its numeric ID")
    async def get_order(order_id: int, include_lines: bool = True) -> Order:
        return await db.orders.find_one(order_id, include_lines=include_lines)

    # Plain Python call still works:
    order = await get_order(order_id=42)

    # Use as an AgenticAPI tool:
    registry = ToolRegistry()
    registry.register(get_order)

The decorator is intentionally backward-compatible: existing
class-based tools (``DatabaseTool``, ``CacheTool`` etc.) keep working
unchanged. The decorator and the class form coexist; users can mix
both styles within one ``ToolRegistry``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast, get_type_hints, overload

from pydantic import ValidationError, create_model

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.base import Tool, ToolCapability, ToolDefinition

F = TypeVar("F", bound=Callable[..., Any])


class _DecoratedTool:
    """Concrete :class:`Tool` produced by :func:`tool`.

    Wraps the user's function while preserving its callability so
    plain Python invocations still work.
    """

    def __init__(
        self,
        *,
        func: Callable[..., Any],
        name: str,
        description: str,
        capabilities: list[ToolCapability],
        parameters_schema: dict[str, Any],
        return_annotation: Any,
    ) -> None:
        self._func = func
        self._is_async = inspect.iscoroutinefunction(func)
        self._definition = ToolDefinition(
            name=name,
            description=description,
            capabilities=capabilities,
            parameters_schema=parameters_schema,
        )
        self._return_annotation = return_annotation

        # Build a Pydantic model for runtime input validation. We
        # construct it lazily on first call to keep import time low
        # for projects with hundreds of tools.
        self._validator_model: Any = None

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def return_annotation(self) -> Any:
        """Return the function's return type annotation, or ``None``.

        Used by future Phase E tasks for typed tool composition.
        """
        return self._return_annotation

    def _ensure_validator(self) -> Any:
        if self._validator_model is None:
            self._validator_model = _build_validator_model(self._func)
        return self._validator_model

    async def invoke(self, **kwargs: Any) -> Any:
        """Validated invocation entry point used by the framework."""
        validator = self._ensure_validator()
        try:
            validated = validator.model_validate(kwargs)
        except ValidationError as exc:
            raise ToolError(f"Invalid arguments for tool '{self._definition.name}': {exc.errors()}") from exc
        call_kwargs = validated.model_dump()
        result = self._func(**call_kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    # Make the decorator transparent: ``my_tool(arg=1)`` keeps working.
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._func(*args, **kwargs)

    # ``isinstance(t, _DecoratedTool)`` for any tests that need it.
    def __repr__(self) -> str:
        return f"<DecoratedTool name={self._definition.name!r}>"


def _build_validator_model(func: Callable[..., Any]) -> Any:
    """Build a Pydantic model that mirrors the function's signature.

    Skips ``self`` if present (for method decorators) and skips any
    parameters that look like AgenticAPI built-in injectables — those
    aren't user-supplied tool arguments.
    """
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}

    fields: dict[str, tuple[Any, Any]] = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        annotation = hints.get(name, param.annotation)
        if annotation is inspect.Parameter.empty:
            annotation = Any
        default = param.default if param.default is not inspect.Parameter.empty else ...
        fields[name] = (annotation, default)

    if not fields:
        # Empty-arg function — produce a schema with no properties.
        return create_model(f"{func.__name__}Args")
    # mypy can't see through pydantic.create_model's variadic field_definitions,
    # but the call is well-formed: each value is the (annotation, default) tuple
    # the function expects.
    return create_model(f"{func.__name__}Args", **fields)  # type: ignore[call-overload]


def _derive_capabilities(func: Callable[..., Any]) -> list[ToolCapability]:
    """Heuristic capability derivation from the function's name + return.

    Errs on the side of READ when the signature is ambiguous so the
    sandbox/policies stay restrictive by default.
    """
    name = func.__name__.lower()
    write_prefixes = ("create_", "delete_", "drop_", "insert_", "update_", "upsert_", "set_", "remove_")
    if any(name.startswith(p) for p in write_prefixes):
        return [ToolCapability.WRITE]
    if name.startswith("search_") or "search" in name:
        return [ToolCapability.SEARCH]
    if name.startswith("aggregate_") or name.startswith("count_") or name.startswith("sum_"):
        return [ToolCapability.AGGREGATE]
    if name.startswith("execute_") or name.startswith("run_"):
        return [ToolCapability.EXECUTE]
    return [ToolCapability.READ]


def _build_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build the JSON Schema describing the function's parameters."""
    model = _build_validator_model(func)
    schema = cast("dict[str, Any]", model.model_json_schema())
    # Pydantic generates a top-level title we don't want; strip it for
    # cleaner LLM-facing schemas.
    schema.pop("title", None)
    return schema


def _derive_description(func: Callable[..., Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    doc = inspect.getdoc(func)
    if doc:
        # First non-empty line of the docstring.
        for line in doc.splitlines():
            if line.strip():
                return line.strip()
    return f"Tool: {func.__name__}"


@overload
def tool(func: F, /) -> Tool: ...  # noqa: UP047 — overloads can't use the new generic syntax cleanly


@overload
def tool(
    *,
    name: str | None = None,
    description: str | None = None,
    capabilities: list[ToolCapability] | None = None,
) -> Callable[[F], Tool]: ...


def tool(
    func: Callable[..., Any] | None = None,
    /,
    *,
    name: str | None = None,
    description: str | None = None,
    capabilities: list[ToolCapability] | None = None,
) -> Any:
    """Decorate a function so it satisfies the :class:`Tool` protocol.

    Args:
        func: The function to decorate. Supplied automatically by the
            ``@tool`` form; supply explicitly when calling
            ``tool(my_func, ...)``.
        name: Optional override for the tool name. Defaults to the
            function's ``__name__``.
        description: Optional override for the tool description.
            Defaults to the first non-empty line of the function's
            docstring, or a generic placeholder.
        capabilities: Optional list of :class:`ToolCapability` values.
            When omitted, capabilities are inferred from the function
            name (e.g. functions starting with ``delete_`` get
            ``WRITE``; everything else defaults to ``READ``).

    Returns:
        An object satisfying the :class:`Tool` protocol that is also
        callable as the original function.
    """

    def _decorate(target: Callable[..., Any]) -> Tool:
        resolved_name = name or target.__name__
        resolved_description = _derive_description(target, description)
        resolved_capabilities = capabilities or _derive_capabilities(target)
        try:
            return_annotation = get_type_hints(target).get("return", None)
        except Exception:
            return_annotation = None
        decorated = _DecoratedTool(
            func=target,
            name=resolved_name,
            description=resolved_description,
            capabilities=resolved_capabilities,
            parameters_schema=_build_parameters_schema(target),
            return_annotation=return_annotation,
        )
        return cast("Tool", decorated)

    if func is not None:
        # Used as ``@tool`` (no parentheses).
        return _decorate(func)
    # Used as ``@tool(...)``.
    return _decorate


__all__ = ["tool"]


# Convenience type alias for callers wanting the decorated form.
DecoratedTool = _DecoratedTool
