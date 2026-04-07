"""Agent-to-Agent protocol message types.

Defines the standard message types used for communication between
coding agents in a distributed AgenticAPI system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class A2AMessageType(StrEnum):
    """Standard A2A protocol message types."""

    DISCOVER = "discover"
    INTENT = "intent"
    NEGOTIATE = "negotiate"
    DELEGATE = "delegate"
    OBSERVE = "observe"
    REVISE = "revise"
    EXPLAIN = "explain"
    VERIFY = "verify"
    RESPONSE = "response"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class A2AMessage:
    """A message in the A2A protocol.

    Attributes:
        message_type: The type of this message.
        sender: Identifier of the sending agent.
        receiver: Identifier of the receiving agent.
        payload: The message payload data.
        correlation_id: ID linking related messages in a conversation.
        metadata: Additional metadata.
    """

    message_type: A2AMessageType
    sender: str
    receiver: str
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class A2ARequest:
    """A request sent to an A2A service.

    Attributes:
        capability_name: The capability being invoked.
        parameters: Request parameters.
        sender: Identifier of the requesting agent.
        correlation_id: ID for tracking the conversation.
        timeout_seconds: Maximum time to wait for a response.
    """

    capability_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    sender: str = ""
    correlation_id: str = ""
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class A2AResponse:
    """A response from an A2A service.

    Attributes:
        success: Whether the request was processed successfully.
        result: The result data.
        error: Error message if unsuccessful.
        correlation_id: ID linking to the original request.
    """

    success: bool
    result: Any = None
    error: str | None = None
    correlation_id: str = ""
