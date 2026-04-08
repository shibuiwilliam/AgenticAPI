"""Agent endpoint definition.

Provides the AgentEndpointDef data class that stores the configuration
for a registered agent endpoint, including handler, policies, and scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

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
