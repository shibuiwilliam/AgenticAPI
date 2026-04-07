"""Approval notification backends.

Defines the protocol for notifying approvers when an approval request
is created, and provides a default log-based implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from agenticapi.harness.approval.workflow import ApprovalRequest

logger = structlog.get_logger(__name__)


@runtime_checkable
class ApprovalNotifier(Protocol):
    """Protocol for approval notification backends.

    Implementations send notifications to approvers when a new
    approval request is created. The framework provides LogNotifier
    as the default; production deployments can implement Slack,
    email, or webhook-based notifiers.
    """

    async def notify(self, request: ApprovalRequest) -> None:
        """Notify approvers about a pending approval request.

        Args:
            request: The approval request requiring attention.
        """
        ...


class LogNotifier:
    """Default notifier that logs approval requests via structlog.

    Suitable for development and testing. Production deployments
    should use a notifier that reaches actual approvers.

    Example:
        notifier = LogNotifier()
        await notifier.notify(approval_request)
    """

    async def notify(self, request: ApprovalRequest) -> None:
        """Log the approval request.

        Args:
            request: The approval request to log.
        """
        logger.info(
            "approval_required",
            request_id=request.request_id,
            trace_id=request.trace_id,
            intent_action=request.intent_action,
            intent_domain=request.intent_domain,
            approvers=request.approvers,
            expires_at=request.expires_at.isoformat(),
        )
