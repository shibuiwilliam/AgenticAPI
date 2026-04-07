"""Approval workflow for human-in-the-loop agent control.

Manages the lifecycle of approval requests: creation, notification,
resolution (approve/reject), and expiration. Uses a raise-and-resume
pattern — ApprovalRequired is raised immediately, and the client
polls or receives a callback when resolved.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import NoReturn

import structlog

from agenticapi.exceptions import ApprovalDenied, ApprovalRequired, ApprovalTimeout
from agenticapi.harness.approval.notifiers import ApprovalNotifier, LogNotifier
from agenticapi.harness.approval.rules import ApprovalRule  # noqa: TC001 (used at runtime)

logger = structlog.get_logger(__name__)


class ApprovalState(StrEnum):
    """State of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ESCALATED = "escalated"


@dataclass(slots=True)
class ApprovalRequest:
    """A pending or resolved approval request.

    Attributes:
        request_id: Unique identifier for this request.
        trace_id: Associated execution trace ID.
        intent_raw: The original natural language request.
        intent_action: The classified action type.
        intent_domain: The domain of the request.
        generated_code: The code awaiting approval.
        rule_name: Name of the rule that triggered approval.
        approvers: List of approver identifiers.
        created_at: When the request was created.
        expires_at: When the request expires.
        state: Current state of the request.
        resolved_by: Who resolved the request (if resolved).
        resolved_at: When the request was resolved (if resolved).
        resolution_reason: Reason for the resolution (if any).
    """

    request_id: str
    trace_id: str
    intent_raw: str
    intent_action: str
    intent_domain: str
    generated_code: str
    rule_name: str
    approvers: list[str]
    created_at: datetime
    expires_at: datetime
    state: ApprovalState = ApprovalState.PENDING
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_reason: str = ""


class ApprovalWorkflow:
    """Manages approval requests lifecycle.

    The workflow checks whether an operation requires approval based
    on configured rules. When approval is required, it creates a
    request, notifies approvers, and raises ApprovalRequired. The
    request can later be resolved via the resolve() method.

    Example:
        workflow = ApprovalWorkflow(rules=[
            ApprovalRule(
                name="write_approval",
                require_for_actions=["write"],
                approvers=["admin"],
            ),
        ])

        rule = workflow.check_approval_required(
            intent_action="write",
            intent_domain="order",
        )
        if rule is not None:
            request = await workflow.create_request(
                rule=rule,
                trace_id="abc123",
                intent_raw="Delete all cancelled orders",
                intent_action="write",
                intent_domain="order",
                generated_code="DELETE FROM orders WHERE status='cancelled'",
            )
            # ApprovalRequired is raised by create_request
    """

    def __init__(
        self,
        *,
        rules: list[ApprovalRule] | None = None,
        notifier: ApprovalNotifier | None = None,
    ) -> None:
        """Initialize the approval workflow.

        Args:
            rules: List of approval rules. If None, no approvals are required.
            notifier: Notification backend. Defaults to LogNotifier.
        """
        self._rules = rules or []
        self._notifier: ApprovalNotifier = notifier or LogNotifier()
        self._requests: dict[str, ApprovalRequest] = {}
        self._resolve_lock = asyncio.Lock()

    @property
    def rules(self) -> list[ApprovalRule]:
        """The configured approval rules."""
        return list(self._rules)

    def check_approval_required(
        self,
        *,
        intent_action: str,
        intent_domain: str,
    ) -> ApprovalRule | None:
        """Check if any rule requires approval for the given intent.

        Returns the first matching rule, or None if no approval is needed.

        Args:
            intent_action: The classified action type.
            intent_domain: The domain of the request.

        Returns:
            The first matching ApprovalRule, or None.
        """
        for rule in self._rules:
            if rule.requires_approval(intent_action=intent_action, intent_domain=intent_domain):
                logger.debug(
                    "approval_rule_matched",
                    rule_name=rule.name,
                    intent_action=intent_action,
                    intent_domain=intent_domain,
                )
                return rule
        return None

    async def create_request(
        self,
        *,
        rule: ApprovalRule,
        trace_id: str,
        intent_raw: str,
        intent_action: str,
        intent_domain: str,
        generated_code: str,
    ) -> NoReturn:
        """Create an approval request and notify approvers.

        Stores the request, sends notifications, and raises
        ApprovalRequired so the caller can return HTTP 202.

        Args:
            rule: The rule that triggered the approval.
            trace_id: The execution trace ID.
            intent_raw: The original natural language request.
            intent_action: The classified action type.
            intent_domain: The domain of the request.
            generated_code: The code awaiting approval.

        Returns:
            The created ApprovalRequest.

        Raises:
            ApprovalRequired: Always raised after creating the request.
        """
        now = datetime.now(tz=UTC)
        request = ApprovalRequest(
            request_id=uuid.uuid4().hex,
            trace_id=trace_id,
            intent_raw=intent_raw,
            intent_action=intent_action,
            intent_domain=intent_domain,
            generated_code=generated_code,
            rule_name=rule.name,
            approvers=list(rule.approvers),
            created_at=now,
            expires_at=now + timedelta(seconds=rule.timeout_seconds),
        )

        self._requests[request.request_id] = request

        logger.info(
            "approval_request_created",
            request_id=request.request_id,
            trace_id=trace_id,
            rule_name=rule.name,
            approvers=rule.approvers,
        )

        await self._notifier.notify(request)

        raise ApprovalRequired(
            f"Approval required by rule '{rule.name}'",
            request_id=request.request_id,
            approvers=list(rule.approvers),
        )

    async def resolve(
        self,
        request_id: str,
        *,
        approved: bool,
        approver: str,
        reason: str = "",
    ) -> ApprovalRequest:
        """Resolve a pending approval request.

        Args:
            request_id: The request to resolve.
            approved: Whether the request is approved or rejected.
            approver: The identifier of the approver.
            reason: Optional reason for the decision.

        Returns:
            The updated ApprovalRequest.

        Raises:
            ValueError: If the request is not found or not pending.
            ApprovalDenied: If the request is rejected.
        """
        async with self._resolve_lock:
            request = self._requests.get(request_id)
            if request is None:
                raise ValueError(f"Approval request '{request_id}' not found")

            # Check expiration
            if request.state == ApprovalState.PENDING and datetime.now(tz=UTC) > request.expires_at:
                request.state = ApprovalState.EXPIRED
                logger.warning("approval_request_expired", request_id=request_id)
                raise ApprovalTimeout(f"Approval request '{request_id}' has expired")

            if request.state != ApprovalState.PENDING:
                raise ValueError(f"Approval request '{request_id}' is not pending (state={request.state})")

            now = datetime.now(tz=UTC)
            request.resolved_by = approver
            request.resolved_at = now
            request.resolution_reason = reason

            if approved:
                request.state = ApprovalState.APPROVED
                logger.info(
                    "approval_request_approved",
                    request_id=request_id,
                    approver=approver,
                )
            else:
                request.state = ApprovalState.REJECTED
                logger.info(
                    "approval_request_rejected",
                    request_id=request_id,
                    approver=approver,
                    reason=reason,
                )
                raise ApprovalDenied(f"Approval request '{request_id}' rejected by {approver}: {reason}")

        return request

    async def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Retrieve an approval request by ID.

        Args:
            request_id: The request identifier.

        Returns:
            The ApprovalRequest, or None if not found.
        """
        return self._requests.get(request_id)

    async def get_pending(self) -> list[ApprovalRequest]:
        """Retrieve all pending approval requests.

        Returns expired requests as expired (updates their state).

        Returns:
            List of pending ApprovalRequest objects.
        """
        now = datetime.now(tz=UTC)
        pending: list[ApprovalRequest] = []
        for request in self._requests.values():
            if request.state == ApprovalState.PENDING:
                if now > request.expires_at:
                    request.state = ApprovalState.EXPIRED
                else:
                    pending.append(request)
        return pending
