"""OpsAgent base class for operational agents.

Ops agents run alongside the application to provide autonomous
operational capabilities such as log analysis, auto-healing,
performance tuning, and incident response.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog

from agenticapi.types import AutonomyLevel, Severity

logger = structlog.get_logger(__name__)


class OpsAgent(ABC):
    """Base class for operational agents.

    Ops agents are registered with AgenticApp via register_ops_agent()
    and participate in the application lifecycle. They start when the
    app starts and stop when the app shuts down.

    Subclasses must implement start(), stop(), and check_health().

    Example:
        class MyOpsAgent(OpsAgent):
            async def start(self) -> None:
                self._running = True

            async def stop(self) -> None:
                self._running = False

            async def check_health(self) -> OpsHealthStatus:
                return OpsHealthStatus(healthy=self._running)

        app = AgenticApp()
        app.register_ops_agent(MyOpsAgent(name="my-agent"))
    """

    def __init__(
        self,
        *,
        name: str,
        autonomy: AutonomyLevel = AutonomyLevel.SUPERVISED,
        max_severity: Severity = Severity.MEDIUM,
    ) -> None:
        """Initialize the ops agent.

        Args:
            name: Unique name identifying this ops agent.
            autonomy: The autonomy level for this agent's actions.
            max_severity: Maximum severity level the agent can handle autonomously.
        """
        self._name = name
        self._autonomy = autonomy
        self._max_severity = max_severity
        self._running = False

    @property
    def name(self) -> str:
        """The unique name of this ops agent."""
        return self._name

    @property
    def autonomy(self) -> AutonomyLevel:
        """The autonomy level for this agent."""
        return self._autonomy

    @property
    def max_severity(self) -> Severity:
        """Maximum severity level handled autonomously."""
        return self._max_severity

    @property
    def running(self) -> bool:
        """Whether the agent is currently running."""
        return self._running

    @abstractmethod
    async def start(self) -> None:
        """Start the ops agent.

        Called during application startup. Implementations should
        initialize background tasks, connect to monitoring systems, etc.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the ops agent.

        Called during application shutdown. Implementations should
        clean up resources and cancel background tasks.
        """
        ...

    @abstractmethod
    async def check_health(self) -> OpsHealthStatus:
        """Check the health of this ops agent.

        Returns:
            The current health status.
        """
        ...

    def can_handle_autonomously(self, severity: Severity) -> bool:
        """Check if the agent can handle an issue at the given severity autonomously.

        Args:
            severity: The severity of the issue.

        Returns:
            True if the agent can act without human approval.
        """
        if self._autonomy == AutonomyLevel.MANUAL:
            return False
        if self._autonomy == AutonomyLevel.AUTO:
            return True
        # SUPERVISED: compare severity levels
        severity_order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        return severity_order.index(severity) <= severity_order.index(self._max_severity)


class OpsHealthStatus:
    """Health status of an ops agent.

    Attributes:
        healthy: Whether the agent is operating normally.
        message: Optional human-readable status message.
        details: Optional additional details.
    """

    def __init__(
        self,
        *,
        healthy: bool = True,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.healthy = healthy
        self.message = message
        self.details = details or {}
