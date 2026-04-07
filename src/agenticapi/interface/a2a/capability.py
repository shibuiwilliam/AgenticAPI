"""A2A capability definitions and negotiation.

Capabilities describe what an agent can do. Other agents discover
and invoke capabilities via the A2A protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Capability:
    """A capability offered by an A2A service.

    Attributes:
        name: Unique name identifying this capability.
        description: Human-readable description of what this capability does.
        input_schema: JSON-schema-like dict describing expected input.
        output_schema: JSON-schema-like dict describing output format.
        sla_max_latency_ms: Maximum expected latency in milliseconds.
        sla_availability: Target availability (0.0-1.0).
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    sla_max_latency_ms: int = 5000
    sla_availability: float = 0.99


class CapabilityRegistry:
    """Registry of capabilities offered by a service.

    Agents register their capabilities here, and remote agents
    can discover them via the A2A DISCOVER message.

    Example:
        registry = CapabilityRegistry()
        registry.register(Capability(
            name="inventory_lookup",
            description="Look up current inventory levels",
        ))
        caps = registry.list_capabilities()
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        """Register a capability.

        Args:
            capability: The capability to register.
        """
        self._capabilities[capability.name] = capability
        logger.info("a2a_capability_registered", capability=capability.name)

    def get(self, name: str) -> Capability | None:
        """Look up a capability by name.

        Args:
            name: The capability name.

        Returns:
            The capability if found, None otherwise.
        """
        return self._capabilities.get(name)

    def list_capabilities(self) -> list[Capability]:
        """List all registered capabilities.

        Returns:
            All registered capabilities.
        """
        return list(self._capabilities.values())

    def has(self, name: str) -> bool:
        """Check if a capability is registered.

        Args:
            name: The capability name.

        Returns:
            True if the capability exists.
        """
        return name in self._capabilities
