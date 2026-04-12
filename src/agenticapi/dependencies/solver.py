"""Resolve an :class:`InjectionPlan` against the live request and call the handler.

This module is the runtime side of the dependency injector. The plan
itself is computed once at handler registration (see
:mod:`agenticapi.dependencies.scanner`); the solver runs on every
request and is responsible for:

1. Filling in built-in injectors (Intent, AgentContext, AgentTasks,
   UploadedFiles, HtmxHeaders) from the live request.
2. Recursively resolving user dependencies declared via
   :func:`agenticapi.dependencies.depends.Depends`.
3. Caching dependency values within one request when ``use_cache=True``.
4. Honouring ``app.dependency_overrides`` for testability.
5. Driving generator-based dependencies' teardown phase after the
   handler returns.

The solver is intentionally minimal and FastAPI-shaped: it does not
yet implement sub-dependency *parallelism* (FastAPI's
``solve_dependencies`` runs sub-deps sequentially too) and it does
not handle ``Annotated[T, Depends(...)]`` syntax in this iteration —
the trailing-default form is enough for v0.2.
"""

from __future__ import annotations

import contextlib
import inspect
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.dependencies.scanner import InjectionKind, scan_handler
from agenticapi.exceptions import AgentRuntimeError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from agenticapi.dependencies.depends import Dependency
    from agenticapi.dependencies.scanner import InjectionPlan
    from agenticapi.interface.intent import Intent
    from agenticapi.interface.tasks import AgentTasks as _AgentTasks
    from agenticapi.runtime.context import AgentContext

logger = structlog.get_logger(__name__)


class DependencyResolutionError(AgentRuntimeError):
    """Raised when a dependency cannot be resolved.

    Carries the dependency call chain so debugging is straightforward.
    """

    def __init__(self, message: str, *, chain: list[str] | None = None) -> None:
        super().__init__(message)
        self.chain = chain or []


@dataclass(slots=True)
class ResolvedHandlerCall:
    """The product of resolving a handler's :class:`InjectionPlan`.

    Attributes:
        kwargs: Keyword arguments to pass to the handler.
        positional: Positional arguments (Intent, AgentContext) for
            handlers using the legacy ``(intent, context)`` shape.
        tasks: The injected :class:`AgentTasks`, or ``None`` if the
            handler did not request one.
        exit_stack: The async exit stack that owns generator-based
            dependency teardown. Must be closed after the handler
            returns (success or failure).
    """

    kwargs: dict[str, Any] = field(default_factory=dict)
    positional: tuple[Any, ...] = ()
    tasks: _AgentTasks | None = None
    exit_stack: AsyncExitStack = field(default_factory=AsyncExitStack)


async def _call_dependency_provider(
    provider: Callable[..., Any],
    sub_kwargs: dict[str, Any],
    exit_stack: AsyncExitStack,
) -> Any:
    """Invoke a single dependency provider, honouring all four shapes.

    The provider may be:

    * a regular sync function (returns the value)
    * an async function (awaits to the value)
    * a sync generator function (yields once; teardown after yield)
    * an async generator function (yields once; teardown after yield)
    """
    if inspect.isasyncgenfunction(provider):
        agen: AsyncIterator[Any] = provider(**sub_kwargs)
        value = await agen.__anext__()

        async def _aclose(_value: Any = value) -> None:
            with contextlib.suppress(StopAsyncIteration):
                await agen.__anext__()

        exit_stack.push_async_callback(_aclose)
        return value

    if inspect.isgeneratorfunction(provider):
        gen: Iterator[Any] = provider(**sub_kwargs)
        value = next(gen)

        async def _close_sync(_value: Any = value) -> None:
            with contextlib.suppress(StopIteration):
                next(gen)

        exit_stack.push_async_callback(_close_sync)
        return value

    result = provider(**sub_kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _resolve_dependency(
    dep: Dependency,
    overrides: dict[Callable[..., Any], Callable[..., Any]],
    cache: dict[Callable[..., Any], Any],
    exit_stack: AsyncExitStack,
    chain: list[str],
) -> Any:
    """Recursively resolve a single :class:`Dependency`."""
    provider: Callable[..., Any] = overrides.get(dep.callable, dep.callable)
    chain.append(getattr(provider, "__qualname__", repr(provider)))

    if len(chain) > 32:
        raise DependencyResolutionError(
            "Dependency resolution chain exceeded depth 32 (likely circular)",
            chain=list(chain),
        )

    if dep.use_cache and provider in cache:
        chain.pop()
        return cache[provider]

    sub_plan = scan_handler(provider)
    sub_kwargs: dict[str, Any] = {}
    for param in sub_plan.params:
        if param.kind is InjectionKind.DEPENDS:
            if param.dependency is None:
                raise DependencyResolutionError(
                    f"Parameter '{param.name}' declared as Depends but has no dependency callable",
                    chain=list(chain),
                )
            sub_kwargs[param.name] = await _resolve_dependency(param.dependency, overrides, cache, exit_stack, chain)
        # Built-in injectors inside dependencies are not supported in
        # this iteration — keep the surface intentionally narrow.

    value = await _call_dependency_provider(provider, sub_kwargs, exit_stack)
    if dep.use_cache:
        cache[provider] = value

    chain.pop()
    return value


async def solve(
    plan: InjectionPlan,
    *,
    intent: Intent[Any],
    context: AgentContext,
    files: dict[str, Any] | None,
    htmx_scope: dict[str, Any] | None,
    overrides: dict[Callable[..., Any], Callable[..., Any]],
    route_dependencies: list[Dependency] | None = None,
    agent_stream: Any | None = None,
) -> ResolvedHandlerCall:
    """Resolve a handler's :class:`InjectionPlan` for one request.

    Args:
        plan: The handler's pre-computed injection plan.
        intent: The parsed agent intent.
        context: The active :class:`AgentContext`.
        files: Uploaded files keyed by form-field name (or ``None``).
        htmx_scope: Raw ASGI scope for HTMX header parsing (or ``None``).
        overrides: ``app.dependency_overrides`` map.
        route_dependencies: Optional list of route-level dependencies
            (D6) to resolve for side effects before the handler runs.
            Their teardown is registered on the same exit stack.
        agent_stream: Optional :class:`AgentStream` instance to inject
            into handlers that declared an ``AgentStream`` parameter.
            Phase F1; ``None`` for non-streaming endpoints.

    Returns:
        A :class:`ResolvedHandlerCall` whose ``exit_stack`` must be
        closed after the handler completes.
    """
    from agenticapi.interface.htmx import HtmxHeaders
    from agenticapi.interface.tasks import AgentTasks

    call = ResolvedHandlerCall()
    cache: dict[Callable[..., Any], Any] = {}
    positional_buffer: list[Any] = []

    # Phase D6: route-level dependencies run first, for side effects
    # only. Their return values are discarded but exceptions propagate
    # up the stack so e.g. an auth check can short-circuit the request
    # by raising AuthenticationError.
    for dep in route_dependencies or ():
        await _resolve_dependency(dep, overrides, cache, call.exit_stack, chain=[])

    for param in plan.params:
        if param.kind is InjectionKind.INTENT:
            call.kwargs[param.name] = intent
        elif param.kind is InjectionKind.CONTEXT:
            call.kwargs[param.name] = context
        elif param.kind is InjectionKind.AGENT_TASKS:
            tasks = AgentTasks()
            call.tasks = tasks
            call.kwargs[param.name] = tasks
        elif param.kind is InjectionKind.UPLOADED_FILES:
            call.kwargs[param.name] = files or {}
        elif param.kind is InjectionKind.HTMX_HEADERS:
            call.kwargs[param.name] = HtmxHeaders.from_scope(htmx_scope or {})
        elif param.kind is InjectionKind.AGENT_STREAM:
            # Phase F1: stream injection. The framework supplies the
            # stream when streaming is enabled on the endpoint.
            # Otherwise we leave it absent — the handler will get a
            # TypeError at call time which is the right diagnostic.
            if agent_stream is not None:
                call.kwargs[param.name] = agent_stream
        elif param.kind is InjectionKind.DEPENDS:
            if param.dependency is None:
                raise DependencyResolutionError(
                    f"Parameter '{param.name}' declared as Depends but has no dependency callable",
                    chain=[],
                )
            call.kwargs[param.name] = await _resolve_dependency(
                param.dependency, overrides, cache, call.exit_stack, chain=[]
            )
        elif param.kind is InjectionKind.POSITIONAL_LEGACY:
            # Fill positional intent / context slots in declaration order.
            positional_buffer.append(intent if len(positional_buffer) == 0 else context)

    call.positional = tuple(positional_buffer)
    return call


async def invoke_handler(
    handler: Callable[..., Awaitable[Any] | Any],
    resolved: ResolvedHandlerCall,
) -> Any:
    """Invoke a handler with a resolved call and await its result.

    Supports both sync and async handlers. Always closes the
    ``exit_stack`` after the handler returns, even on failure, so
    generator-style teardown runs reliably.
    """
    try:
        result = handler(*resolved.positional, **resolved.kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
    finally:
        await resolved.exit_stack.aclose()


__all__ = [
    "DependencyResolutionError",
    "ResolvedHandlerCall",
    "invoke_handler",
    "solve",
]
