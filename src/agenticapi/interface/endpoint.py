"""Agent endpoint definition.

Provides the AgentEndpointDef data class that stores the configuration
for a registered agent endpoint, including handler, policies, and scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

    from agenticapi.dependencies.depends import Dependency
    from agenticapi.dependencies.scanner import InjectionPlan
    from agenticapi.harness.policy.autonomy_policy import AutonomyPolicy
    from agenticapi.harness.policy.base import Policy
    from agenticapi.interface.intent import IntentScope
    from agenticapi.security import Authenticator


@dataclass(slots=True)
class AgentEndpointDef:
    """Definition of a registered agent endpoint.

    Stores the handler function and all configuration for an agent
    endpoint, including scope constraints, policies, and autonomy level.

    Attributes:
        name: Unique name for this endpoint.
        handler: The async handler function for this endpoint.
        description: Human-readable description.
        intent_scope: Optional scope constraints for allowed intents.
        autonomy_level: Agent autonomy level ("auto", "supervised", "manual").
        policies: List of policies to enforce on this endpoint.
        approval: Optional approval workflow configuration.
        sandbox: Optional sandbox configuration override.
        enable_mcp: Whether to expose this endpoint as an MCP tool.
        auth: Optional Authenticator for this endpoint.
        response_model: Optional Pydantic model the handler return is
            validated against. When set, the model schema is also
            published in OpenAPI for this endpoint.
        injection_plan: Cached injection plan for the handler. Computed
            lazily by the framework on first use.
        dependencies: Optional list of route-level dependencies that
            run for side effects before the handler. Their return
            values are discarded — they are useful for cross-cutting
            concerns (auth checks, rate limiting, audit hooks) that
            should not pollute the handler signature.
        streaming: Optional streaming transport for this endpoint.
            ``None`` (default) → the handler returns a single
            ``AgentResponse`` JSON blob (legacy behaviour). ``"sse"``
            → the framework wraps the handler in a Server-Sent Events
            stream consuming the handler's :class:`AgentStream`.
            Future: ``"ndjson"``, ``"websocket"``. Phase F2.
        autonomy: Optional :class:`AutonomyPolicy` (Phase F6) with
            live-escalation rules. When set, the framework builds an
            :class:`~agenticapi.harness.policy.autonomy_policy.AutonomyState`
            per request, attaches it to the :class:`AgentStream`, and
            lets the handler feed live signals through
            ``stream.report_signal(...)``. Escalations produce
            typed ``AutonomyChangedEvent``s on the wire + in the
            audit trace. When ``None``, the static ``autonomy_level``
            string is the fallback for approval decisions.
    """

    name: str
    handler: Callable[..., Any]
    description: str = ""
    intent_scope: IntentScope | None = None
    autonomy_level: str = "supervised"
    policies: list[Policy] = field(default_factory=list)
    approval: Any | None = None
    sandbox: Any | None = None
    enable_mcp: bool = False
    auth: Authenticator | None = None
    response_model: type[BaseModel] | None = None
    injection_plan: InjectionPlan | None = None
    dependencies: list[Dependency] = field(default_factory=list)
    streaming: str | None = None
    autonomy: AutonomyPolicy | None = None
