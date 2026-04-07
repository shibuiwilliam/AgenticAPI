"""Tests for A2A protocol message types."""

from __future__ import annotations

from agenticapi.interface.a2a.protocol import (
    A2AMessage,
    A2AMessageType,
    A2ARequest,
    A2AResponse,
)


class TestA2AMessageType:
    def test_all_types_exist(self) -> None:
        assert A2AMessageType.DISCOVER == "discover"
        assert A2AMessageType.INTENT == "intent"
        assert A2AMessageType.NEGOTIATE == "negotiate"
        assert A2AMessageType.DELEGATE == "delegate"
        assert A2AMessageType.OBSERVE == "observe"
        assert A2AMessageType.REVISE == "revise"
        assert A2AMessageType.EXPLAIN == "explain"
        assert A2AMessageType.VERIFY == "verify"
        assert A2AMessageType.RESPONSE == "response"
        assert A2AMessageType.ERROR == "error"


class TestA2AMessage:
    def test_create_message(self) -> None:
        msg = A2AMessage(
            message_type=A2AMessageType.INTENT,
            sender="agent-a",
            receiver="agent-b",
            payload={"action": "read"},
            correlation_id="corr-1",
        )
        assert msg.message_type == A2AMessageType.INTENT
        assert msg.sender == "agent-a"
        assert msg.receiver == "agent-b"
        assert msg.payload == {"action": "read"}
        assert msg.correlation_id == "corr-1"

    def test_defaults(self) -> None:
        msg = A2AMessage(
            message_type=A2AMessageType.DISCOVER,
            sender="a",
            receiver="b",
        )
        assert msg.payload == {}
        assert msg.correlation_id == ""
        assert msg.metadata == {}

    def test_frozen(self) -> None:
        msg = A2AMessage(message_type=A2AMessageType.DISCOVER, sender="a", receiver="b")
        try:
            msg.sender = "c"  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestA2ARequest:
    def test_create(self) -> None:
        req = A2ARequest(
            capability_name="inventory_lookup",
            parameters={"product_id": "123"},
            sender="agent-a",
        )
        assert req.capability_name == "inventory_lookup"
        assert req.parameters == {"product_id": "123"}

    def test_defaults(self) -> None:
        req = A2ARequest(capability_name="test")
        assert req.parameters == {}
        assert req.sender == ""
        assert req.timeout_seconds == 30.0


class TestA2AResponse:
    def test_success(self) -> None:
        resp = A2AResponse(success=True, result={"count": 42})
        assert resp.success is True
        assert resp.result == {"count": 42}
        assert resp.error is None

    def test_failure(self) -> None:
        resp = A2AResponse(success=False, error="Not found")
        assert resp.success is False
        assert resp.error == "Not found"
