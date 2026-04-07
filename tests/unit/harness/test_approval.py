"""Tests for approval workflow: rules, workflow, and notifiers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agenticapi.exceptions import ApprovalDenied, ApprovalRequired, ApprovalTimeout
from agenticapi.harness.approval.notifiers import LogNotifier
from agenticapi.harness.approval.rules import ApprovalRule
from agenticapi.harness.approval.workflow import (
    ApprovalRequest,
    ApprovalState,
    ApprovalWorkflow,
)

# --- ApprovalRule tests ---


class TestApprovalRule:
    def test_requires_approval_for_write_action(self) -> None:
        rule = ApprovalRule(name="test", require_for_actions=["write"])
        assert rule.requires_approval(intent_action="write", intent_domain="order") is True

    def test_does_not_require_approval_for_read_action(self) -> None:
        rule = ApprovalRule(name="test", require_for_actions=["write"])
        assert rule.requires_approval(intent_action="read", intent_domain="order") is False

    def test_default_actions_include_write_and_execute(self) -> None:
        rule = ApprovalRule(name="test")
        assert rule.requires_approval(intent_action="write", intent_domain="any") is True
        assert rule.requires_approval(intent_action="execute", intent_domain="any") is True
        assert rule.requires_approval(intent_action="read", intent_domain="any") is False

    def test_domain_filter_matches(self) -> None:
        rule = ApprovalRule(
            name="test",
            require_for_actions=["write"],
            require_for_domains=["order"],
        )
        assert rule.requires_approval(intent_action="write", intent_domain="order") is True
        assert rule.requires_approval(intent_action="write", intent_domain="product") is False

    def test_empty_domain_filter_matches_all(self) -> None:
        rule = ApprovalRule(name="test", require_for_actions=["write"])
        assert rule.requires_approval(intent_action="write", intent_domain="anything") is True

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            ApprovalRule(name="test", unknown_field="value")  # type: ignore[call-arg]


# --- ApprovalWorkflow tests ---


class TestApprovalWorkflowCheckRequired:
    def test_returns_matching_rule(self) -> None:
        rule = ApprovalRule(name="write_rule", require_for_actions=["write"])
        workflow = ApprovalWorkflow(rules=[rule])
        result = workflow.check_approval_required(intent_action="write", intent_domain="order")
        assert result is not None
        assert result.name == "write_rule"

    def test_returns_none_when_no_match(self) -> None:
        rule = ApprovalRule(name="write_rule", require_for_actions=["write"])
        workflow = ApprovalWorkflow(rules=[rule])
        result = workflow.check_approval_required(intent_action="read", intent_domain="order")
        assert result is None

    def test_returns_first_matching_rule(self) -> None:
        rule1 = ApprovalRule(name="first", require_for_actions=["write"])
        rule2 = ApprovalRule(name="second", require_for_actions=["write"])
        workflow = ApprovalWorkflow(rules=[rule1, rule2])
        result = workflow.check_approval_required(intent_action="write", intent_domain="any")
        assert result is not None
        assert result.name == "first"

    def test_returns_none_with_no_rules(self) -> None:
        workflow = ApprovalWorkflow()
        result = workflow.check_approval_required(intent_action="write", intent_domain="order")
        assert result is None


class TestApprovalWorkflowCreateRequest:
    async def test_create_request_raises_approval_required(self) -> None:
        rule = ApprovalRule(name="test_rule", require_for_actions=["write"], approvers=["admin"])
        workflow = ApprovalWorkflow(rules=[rule])

        with pytest.raises(ApprovalRequired) as exc_info:
            await workflow.create_request(
                rule=rule,
                trace_id="trace_123",
                intent_raw="delete orders",
                intent_action="write",
                intent_domain="order",
                generated_code="DELETE FROM orders",
            )

        assert exc_info.value.request_id is not None
        assert exc_info.value.approvers == ["admin"]

    async def test_create_request_stores_request(self) -> None:
        rule = ApprovalRule(name="test_rule", require_for_actions=["write"], approvers=["admin"])
        workflow = ApprovalWorkflow(rules=[rule])

        try:
            await workflow.create_request(
                rule=rule,
                trace_id="trace_123",
                intent_raw="delete orders",
                intent_action="write",
                intent_domain="order",
                generated_code="DELETE FROM orders",
            )
        except ApprovalRequired as exc:
            request = await workflow.get_request(exc.request_id)  # type: ignore[arg-type]
            assert request is not None
            assert request.state == ApprovalState.PENDING
            assert request.intent_raw == "delete orders"
            assert request.generated_code == "DELETE FROM orders"
            assert request.rule_name == "test_rule"

    async def test_create_request_appears_in_pending(self) -> None:
        import contextlib

        rule = ApprovalRule(name="test_rule", require_for_actions=["write"])
        workflow = ApprovalWorkflow(rules=[rule])

        with contextlib.suppress(ApprovalRequired):
            await workflow.create_request(
                rule=rule,
                trace_id="trace_1",
                intent_raw="delete",
                intent_action="write",
                intent_domain="order",
                generated_code="DELETE FROM orders",
            )

        pending = await workflow.get_pending()
        assert len(pending) == 1


class TestApprovalWorkflowResolve:
    async def _create_pending_request(self, workflow: ApprovalWorkflow) -> str:
        """Helper to create a pending request and return its ID."""
        rule = ApprovalRule(name="test", require_for_actions=["write"], approvers=["admin"])
        try:
            await workflow.create_request(
                rule=rule,
                trace_id="trace",
                intent_raw="test",
                intent_action="write",
                intent_domain="order",
                generated_code="code",
            )
        except ApprovalRequired as exc:
            return exc.request_id  # type: ignore[return-value]
        raise AssertionError("ApprovalRequired not raised")

    async def test_approve_request(self) -> None:
        workflow = ApprovalWorkflow()
        request_id = await self._create_pending_request(workflow)

        result = await workflow.resolve(request_id, approved=True, approver="admin")
        assert result.state == ApprovalState.APPROVED
        assert result.resolved_by == "admin"
        assert result.resolved_at is not None

    async def test_reject_request_raises_approval_denied(self) -> None:
        workflow = ApprovalWorkflow()
        request_id = await self._create_pending_request(workflow)

        with pytest.raises(ApprovalDenied, match="rejected"):
            await workflow.resolve(request_id, approved=False, approver="admin", reason="too risky")

        request = await workflow.get_request(request_id)
        assert request is not None
        assert request.state == ApprovalState.REJECTED
        assert request.resolution_reason == "too risky"

    async def test_resolve_nonexistent_raises_value_error(self) -> None:
        workflow = ApprovalWorkflow()
        with pytest.raises(ValueError, match="not found"):
            await workflow.resolve("nonexistent", approved=True, approver="admin")

    async def test_resolve_already_resolved_raises_value_error(self) -> None:
        workflow = ApprovalWorkflow()
        request_id = await self._create_pending_request(workflow)
        await workflow.resolve(request_id, approved=True, approver="admin")

        with pytest.raises(ValueError, match="not pending"):
            await workflow.resolve(request_id, approved=True, approver="admin2")

    async def test_resolve_expired_raises_timeout(self) -> None:
        workflow = ApprovalWorkflow()
        request_id = await self._create_pending_request(workflow)

        # Manually expire the request
        request = await workflow.get_request(request_id)
        assert request is not None
        request.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)

        with pytest.raises(ApprovalTimeout, match="expired"):
            await workflow.resolve(request_id, approved=True, approver="admin")


class TestApprovalWorkflowPending:
    async def test_get_pending_excludes_expired(self) -> None:
        rule = ApprovalRule(name="test", require_for_actions=["write"], timeout_seconds=60)
        workflow = ApprovalWorkflow(rules=[rule])

        try:
            await workflow.create_request(
                rule=rule,
                trace_id="t1",
                intent_raw="test",
                intent_action="write",
                intent_domain="order",
                generated_code="code",
            )
        except ApprovalRequired as exc:
            request = await workflow.get_request(exc.request_id)  # type: ignore[arg-type]
            assert request is not None
            request.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)

        pending = await workflow.get_pending()
        assert len(pending) == 0


# --- ApprovalState tests ---


class TestApprovalState:
    def test_enum_values(self) -> None:
        assert ApprovalState.PENDING == "pending"
        assert ApprovalState.APPROVED == "approved"
        assert ApprovalState.REJECTED == "rejected"
        assert ApprovalState.EXPIRED == "expired"
        assert ApprovalState.ESCALATED == "escalated"


# --- LogNotifier tests ---


class TestLogNotifier:
    async def test_notify_does_not_raise(self) -> None:
        notifier = LogNotifier()
        request = ApprovalRequest(
            request_id="req_1",
            trace_id="trace_1",
            intent_raw="test request",
            intent_action="write",
            intent_domain="order",
            generated_code="DELETE FROM orders",
            rule_name="test_rule",
            approvers=["admin"],
            created_at=datetime.now(tz=UTC),
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        )
        # Should not raise
        await notifier.notify(request)
