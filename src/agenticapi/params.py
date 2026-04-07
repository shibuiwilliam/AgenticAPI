"""Dependency injection helpers for AgenticAPI.

Provides HarnessDepends and related markers for declaring
dependencies in agent endpoint handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class HarnessDepends:
    """Dependency injection marker for harness components.

    Analogous to FastAPI's Depends(). Marks a parameter as requiring
    injection of a harness-related dependency at runtime.

    Example:
        @app.agent_endpoint(name="users")
        async def user_agent(
            intent: Intent,
            context: AgentContext,
            harness: HarnessEngine = HarnessDepends(get_harness),
        ):
            ...
    """

    def __init__(self, dependency: Callable[..., Any]) -> None:
        """Initialize the dependency marker.

        Args:
            dependency: A callable that provides the dependency value.
        """
        self.dependency = dependency

    def __repr__(self) -> str:
        return f"HarnessDepends({self.dependency!r})"
