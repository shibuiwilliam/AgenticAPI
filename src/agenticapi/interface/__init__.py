"""Interface layer for AgenticAPI.

The interface layer handles incoming requests, converting them into
structured Intent objects and returning formatted AgentResponse objects.

Re-exports key types for convenient access.
"""

from __future__ import annotations

from agenticapi.interface.endpoint import AgentEndpointDef
from agenticapi.interface.htmx import HtmxHeaders
from agenticapi.interface.intent import Intent, IntentAction, IntentParser, IntentScope
from agenticapi.interface.response import AgentResponse, FileResult, HTMLResult, PlainTextResult, ResponseFormatter
from agenticapi.interface.session import Session, SessionManager
from agenticapi.interface.stream import (
    AgentEvent,
    AgentStream,
    ApprovalHandle,
    ApprovalRequestedEvent,
    ApprovalResolvedEvent,
    AutonomyChangedEvent,
    ErrorEvent,
    FinalEvent,
    PartialResultEvent,
    ThoughtEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agenticapi.interface.stream_store import InMemoryStreamStore, StreamStore
from agenticapi.interface.tasks import AgentTasks
from agenticapi.interface.upload import UploadedFiles, UploadFile

__all__ = [
    "AgentEndpointDef",
    "AgentEvent",
    "AgentResponse",
    "AgentStream",
    "AgentTasks",
    "ApprovalHandle",
    "ApprovalRequestedEvent",
    "ApprovalResolvedEvent",
    "AutonomyChangedEvent",
    "ErrorEvent",
    "FileResult",
    "FinalEvent",
    "HTMLResult",
    "HtmxHeaders",
    "InMemoryStreamStore",
    "Intent",
    "IntentAction",
    "IntentParser",
    "IntentScope",
    "PartialResultEvent",
    "PlainTextResult",
    "ResponseFormatter",
    "Session",
    "SessionManager",
    "StreamStore",
    "ThoughtEvent",
    "ToolCallCompletedEvent",
    "ToolCallStartedEvent",
    "UploadFile",
    "UploadedFiles",
]
