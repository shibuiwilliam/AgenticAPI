"""AgentMesh — multi-agent orchestration container.

``AgentMesh`` wraps an ``AgenticApp`` and provides ``@mesh.role`` and
``@mesh.orchestrator`` decorators for composing multiple agent
functions into a governed pipeline.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.interface.intent import Intent  # noqa: TC001 — used at runtime in wrapper
from agenticapi.interface.response import AgentResponse
from agenticapi.mesh.context import MeshContext
from agenticapi.runtime.context import AgentContext  # noqa: TC001 — used at runtime in wrapper

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic import BaseModel

    from agenticapi.app import AgenticApp

logger = structlog.get_logger(__name__)


class AgentMesh:
    """Multi-agent orchestration container.

    Wraps an ``AgenticApp`` and provides decorators for declaring
    agent roles and orchestrators. Roles are in-process handlers
    that can be called by orchestrators via ``MeshContext.call()``.

    Example::

        app = AgenticApp(title="Research")
        mesh = AgentMesh(app=app, name="research")

        @mesh.role(name="researcher")
        async def researcher(payload, ctx):
            return {"topic": str(payload), "points": ["a", "b"]}

        @mesh.orchestrator(name="pipeline", roles=["researcher"])
        async def pipeline(intent, mesh_ctx):
            return await mesh_ctx.call("researcher", intent.raw)

    Args:
        app: The ``AgenticApp`` to register endpoints on.
        name: A human-readable name for this mesh.
    """

    def __init__(self, *, app: AgenticApp, name: str = "mesh") -> None:
        self._app = app
        self._name = name
        self._roles: dict[str, Callable[..., Awaitable[Any]]] = {}
        self._orchestrators: dict[str, Callable[..., Awaitable[Any]]] = {}

    @property
    def name(self) -> str:
        """The mesh name."""
        return self._name

    @property
    def roles(self) -> list[str]:
        """Names of all registered roles."""
        return sorted(self._roles)

    def role(
        self,
        name: str,
        *,
        response_model: type[BaseModel] | None = None,
        description: str = "",
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Register a mesh role.

        A role is a lightweight agent handler invokable via
        ``MeshContext.call(role_name, payload)``. It is also exposed
        as a standalone ``/agent/{name}`` endpoint on the parent app.

        Args:
            name: Unique role name within this mesh.
            response_model: Optional Pydantic model for response
                validation.
            description: Human-readable description.

        Returns:
            Decorator that registers the handler.
        """

        def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            if name in self._roles:
                msg = f"Mesh role '{name}' is already registered."
                raise ValueError(msg)

            self._roles[name] = fn

            # Also register as a regular agent endpoint.
            @self._app.agent_endpoint(
                name=name,
                description=description or f"Mesh role: {name}",
                response_model=response_model,
            )
            async def _endpoint_wrapper(intent: Intent[Any], context: AgentContext) -> AgentResponse:
                mesh_ctx = MeshContext(
                    mesh=self,
                    trace_id=getattr(context, "trace_id", uuid.uuid4().hex),
                )
                result = await fn(intent.raw, mesh_ctx)
                return AgentResponse(result=result, reasoning=f"Mesh role '{name}'")

            logger.info("mesh_role_registered", mesh=self._name, role=name)
            return fn

        return decorator

    def orchestrator(
        self,
        name: str,
        *,
        roles: list[str] | None = None,
        description: str = "",
        budget_usd: float | None = None,
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Register a mesh orchestrator.

        An orchestrator is an agent handler that receives a
        ``MeshContext`` and can call other roles via
        ``mesh_ctx.call()``.

        Args:
            name: Unique orchestrator name.
            roles: Optional list of role names this orchestrator
                is expected to call (documentation only — not enforced).
            description: Human-readable description.
            budget_usd: Optional total budget for sub-agent calls.

        Returns:
            Decorator that registers the handler.
        """

        def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            if name in self._orchestrators:
                msg = f"Mesh orchestrator '{name}' is already registered."
                raise ValueError(msg)

            self._orchestrators[name] = fn

            @self._app.agent_endpoint(
                name=name,
                description=description or f"Mesh orchestrator: {name}",
            )
            async def _orch_wrapper(intent: Intent[Any], context: AgentContext) -> AgentResponse:
                mesh_ctx = MeshContext(
                    mesh=self,
                    trace_id=getattr(context, "trace_id", uuid.uuid4().hex),
                    parent_budget_remaining_usd=budget_usd,
                    call_stack=[],
                )
                result = await fn(intent, mesh_ctx)
                if isinstance(result, AgentResponse):
                    return result
                return AgentResponse(result=result, reasoning=f"Mesh orchestrator '{name}'")

            logger.info(
                "mesh_orchestrator_registered",
                mesh=self._name,
                orchestrator=name,
                declared_roles=roles or [],
            )
            return fn

        return decorator
