"""Approval rules for determining when human approval is required.

Defines declarative rules that specify which agent operations need
human approval before execution. Rules match against intent action
and domain to decide if approval is needed.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class ApprovalRule(BaseModel):
    """Rule that determines if an operation requires human approval.

    Each rule specifies which intent actions and domains trigger
    the approval requirement, who can approve, and the timeout.

    Example:
        rule = ApprovalRule(
            name="write_approval",
            require_for_actions=["write", "execute"],
            approvers=["db_admin"],
            timeout_seconds=1800,
        )
        if rule.requires_approval(intent_action="write", intent_domain="order"):
            # Trigger approval workflow
            ...
    """

    model_config = {"extra": "forbid"}

    name: str = Field(description="Unique name for this approval rule.")
    require_for_actions: list[str] = Field(
        default_factory=lambda: ["write", "execute"],
        description="Intent actions that require approval.",
    )
    require_for_domains: list[str] = Field(
        default_factory=list,
        description="Intent domains that require approval. Empty means all domains.",
    )
    approvers: list[str] = Field(
        default_factory=list,
        description="List of approver identifiers (roles or user IDs).",
    )
    timeout_seconds: int = Field(
        default=3600,
        ge=60,
        description="Approval timeout in seconds.",
    )
    require_all_approvers: bool = Field(
        default=False,
        description="Whether all approvers must approve (True) or just one (False).",
    )

    def requires_approval(self, *, intent_action: str, intent_domain: str) -> bool:
        """Check if this rule requires approval for the given intent.

        Args:
            intent_action: The classified action type (e.g., "read", "write").
            intent_domain: The domain of the request (e.g., "order", "product").

        Returns:
            True if this rule requires approval for the given intent.
        """
        action_match = intent_action in self.require_for_actions
        if not action_match:
            return False

        if self.require_for_domains:
            return intent_domain in self.require_for_domains

        return True
