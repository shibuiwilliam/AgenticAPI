"""``Depends()`` marker and ``Dependency`` dataclass.

This module provides the marker users place in handler signatures to opt
into dependency injection. The shape mirrors FastAPI's ``Depends()`` so
that developers familiar with FastAPI feel immediately at home.

Example:
    async def get_db() -> AsyncIterator[Connection]:
        async with engine.connect() as conn:
            yield conn

    @app.agent_endpoint(name="orders")
    async def list_orders(
        intent: Intent,
        context: AgentContext,
        db: Connection = Depends(get_db),
    ) -> dict[str, Any]:
        ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Dependency:
    """A resolved dependency description.

    Carries the user-supplied callable plus its options. The runtime
    solver consumes these to build the per-request injection plan.

    Attributes:
        callable: The dependency provider. May be sync, async, a
            sync generator (yield-based teardown), or an async
            generator (async yield-based teardown).
        use_cache: When True (default), the same dependency callable
            yields the same value within one request. When False, the
            callable is invoked on every reference within the request.
    """

    callable: Callable[..., Any]
    use_cache: bool = True


def Depends(  # noqa: N802, UP047 — name mirrors FastAPI's public API on purpose
    dependency: Callable[..., T],
    *,
    use_cache: bool = True,
) -> T:
    """Marker placed as the default value of a handler/dependency parameter.

    The return type is annotated as ``T`` so the IDE and type checker
    treat the parameter as the resolved dependency type, not as a
    :class:`Dependency` sentinel. At runtime the function returns a
    :class:`Dependency` object that the scanner picks up.

    Args:
        dependency: A callable that produces the dependency. May be a
            plain function, an async function, a sync generator, or an
            async generator. Generators get teardown semantics —
            anything after ``yield`` runs after the handler finishes.
        use_cache: When True (default), repeated references to the
            same callable within one request return the cached value.
            Set to False for resources that must be fresh per use
            (e.g. random IDs, timestamps).

    Returns:
        Statically typed as ``T``, the dependency's resolved value.
        At runtime returns a :class:`Dependency` sentinel.
    """
    return cast("T", Dependency(callable=dependency, use_cache=use_cache))


__all__ = ["Dependency", "Depends"]
