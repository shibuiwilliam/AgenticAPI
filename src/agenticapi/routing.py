"""Agent router for grouping endpoints.

Provides AgentRouter, analogous to FastAPI's APIRouter, for organizing
agent endpoints into logical groups with shared configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi.dependencies import scan_handler
from agenticapi.interface.endpoint import AgentEndpointDef

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

    from agenticapi.dependencies.depends import Dependency
    from agenticapi.harness.policy.autonomy_policy import AutonomyPolicy
    from agenticapi.interface.intent import IntentScope
    from agenticapi.security import Authenticator


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
        auth: Authenticator | None = None,
    ) -> None:
        """Initialize the router.

        Args:
            prefix: Prefix to prepend to all endpoint names.
            tags: Optional tags for documentation/grouping.
            auth: Optional default Authenticator for all endpoints on this router.
        """
        self._prefix = prefix
        self._tags = tags or []
        self._auth: Authenticator | None = auth
        self._endpoints: dict[str, AgentEndpointDef] = {}

    def agent_endpoint(
        self,
        name: str,
        *,
        description: str = "",
        intent_scope: IntentScope | None = None,
        autonomy_level: str = "supervised",
        autonomy: AutonomyPolicy | None = None,
        policies: list[Any] | None = None,
        approval: Any | None = None,
        sandbox: Any | None = None,
        enable_mcp: bool = False,
        auth: Authenticator | None = None,
        response_model: type[BaseModel] | None = None,
        dependencies: list[Dependency] | None = None,
        streaming: str | None = None,
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
            enable_mcp: Whether to expose this endpoint as an MCP tool.
            auth: Optional Authenticator for this endpoint. Overrides router-level auth.
            response_model: Optional Pydantic model for handler return validation.
            dependencies: Optional list of route-level dependencies
                that run before the handler for side effects only.

        Returns:
            A decorator that registers the handler function.
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            full_name = f"{self._prefix}.{name}" if self._prefix else name
            effective_autonomy_level = autonomy.start.value if autonomy is not None else autonomy_level
            self._endpoints[full_name] = AgentEndpointDef(
                name=full_name,
                handler=func,
                description=description,
                intent_scope=intent_scope,
                autonomy_level=effective_autonomy_level,
                autonomy=autonomy,
                policies=policies or [],
                approval=approval,
                sandbox=sandbox,
                enable_mcp=enable_mcp,
                auth=auth or self._auth,
                response_model=response_model,
                injection_plan=scan_handler(func),
                dependencies=list(dependencies or []),
                streaming=streaming,
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
