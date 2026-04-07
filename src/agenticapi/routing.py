"""Agent router for grouping endpoints.

Provides AgentRouter, analogous to FastAPI's APIRouter, for organizing
agent endpoints into logical groups with shared configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi.interface.endpoint import AgentEndpointDef

if TYPE_CHECKING:
    from collections.abc import Callable

    from agenticapi.interface.intent import IntentScope


class AgentRouter:
    """Router for grouping agent endpoints.

    Analogous to FastAPI's APIRouter. Allows organizing endpoints
    into logical groups with a shared prefix and tags.

    Example:
        router = AgentRouter(prefix="orders", tags=["orders"])

        @router.agent_endpoint(name="query")
        async def order_query(intent, context):
            ...

        app.include_router(router)
    """

    def __init__(
        self,
        *,
        prefix: str = "",
        tags: list[str] | None = None,
    ) -> None:
        """Initialize the router.

        Args:
            prefix: Prefix to prepend to all endpoint names.
            tags: Optional tags for documentation/grouping.
        """
        self._prefix = prefix
        self._tags = tags or []
        self._endpoints: dict[str, AgentEndpointDef] = {}

    def agent_endpoint(
        self,
        name: str,
        *,
        description: str = "",
        intent_scope: IntentScope | None = None,
        autonomy_level: str = "supervised",
        policies: list[Any] | None = None,
        approval: Any | None = None,
        sandbox: Any | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register an agent endpoint on this router.

        Works as a decorator, same as AgenticApp.agent_endpoint.

        Args:
            name: Name of the endpoint.
            description: Human-readable description.
            intent_scope: Optional scope constraints.
            autonomy_level: Agent autonomy level.
            policies: List of policies to enforce.
            approval: Optional approval workflow configuration.
            sandbox: Optional sandbox configuration.

        Returns:
            A decorator that registers the handler function.
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            full_name = f"{self._prefix}.{name}" if self._prefix else name
            self._endpoints[full_name] = AgentEndpointDef(
                name=full_name,
                handler=func,
                description=description,
                intent_scope=intent_scope,
                autonomy_level=autonomy_level,
                policies=policies or [],
                approval=approval,
                sandbox=sandbox,
            )
            return func

        return decorator

    @property
    def endpoints(self) -> dict[str, AgentEndpointDef]:
        """All registered endpoints on this router."""
        return dict(self._endpoints)

    @property
    def prefix(self) -> str:
        """The router's prefix."""
        return self._prefix

    @property
    def tags(self) -> list[str]:
        """The router's tags."""
        return list(self._tags)
