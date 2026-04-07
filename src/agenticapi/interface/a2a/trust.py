"""A2A trust scoring and policy.

Manages trust levels between agents, controlling what operations
a remote agent is permitted to perform.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    """Policy governing trust between agents.

    Attributes:
        initial_trust: Trust score for unknown agents (0.0-1.0).
        min_trust_for_read: Minimum trust to allow read operations.
        min_trust_for_write: Minimum trust to allow write operations.
        decay_per_failure: How much trust decreases on failure.
        gain_per_success: How much trust increases on success.
    """

    initial_trust: float = 0.5
    min_trust_for_read: float = 0.3
    min_trust_for_write: float = 0.8
    decay_per_failure: float = 0.1
    gain_per_success: float = 0.05


class TrustScorer:
    """Tracks and computes trust scores for remote agents.

    Trust scores are updated based on interaction outcomes and
    used to gate what operations remote agents can perform.

    Example:
        scorer = TrustScorer(policy=TrustPolicy())
        score = scorer.get_score("agent-123")
        scorer.record_success("agent-123")
    """

    def __init__(self, *, policy: TrustPolicy | None = None) -> None:
        """Initialize the trust scorer.

        Args:
            policy: The trust policy to apply. Uses defaults if None.
        """
        self._policy = policy or TrustPolicy()
        self._scores: dict[str, float] = {}

    @property
    def policy(self) -> TrustPolicy:
        """The active trust policy."""
        return self._policy

    def get_score(self, agent_id: str) -> float:
        """Get the trust score for an agent.

        Args:
            agent_id: The agent identifier.

        Returns:
            The trust score (0.0-1.0). Returns initial_trust for unknown agents.
        """
        return self._scores.get(agent_id, self._policy.initial_trust)

    def can_read(self, agent_id: str) -> bool:
        """Check if an agent is trusted enough for read operations.

        Args:
            agent_id: The agent identifier.

        Returns:
            True if the agent meets the minimum read trust threshold.
        """
        return self.get_score(agent_id) >= self._policy.min_trust_for_read

    def can_write(self, agent_id: str) -> bool:
        """Check if an agent is trusted enough for write operations.

        Args:
            agent_id: The agent identifier.

        Returns:
            True if the agent meets the minimum write trust threshold.
        """
        return self.get_score(agent_id) >= self._policy.min_trust_for_write

    def record_success(self, agent_id: str) -> float:
        """Record a successful interaction, increasing trust.

        Args:
            agent_id: The agent identifier.

        Returns:
            The updated trust score.
        """
        current = self.get_score(agent_id)
        new_score = min(1.0, current + self._policy.gain_per_success)
        self._scores[agent_id] = new_score
        logger.debug("trust_updated", agent_id=agent_id, old=current, new=new_score, reason="success")
        return new_score

    def record_failure(self, agent_id: str) -> float:
        """Record a failed interaction, decreasing trust.

        Args:
            agent_id: The agent identifier.

        Returns:
            The updated trust score.
        """
        current = self.get_score(agent_id)
        new_score = max(0.0, current - self._policy.decay_per_failure)
        self._scores[agent_id] = new_score
        logger.debug("trust_updated", agent_id=agent_id, old=current, new=new_score, reason="failure")
        return new_score
