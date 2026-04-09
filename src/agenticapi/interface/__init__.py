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
from agenticapi.interface.tasks import AgentTasks
from agenticapi.interface.upload import UploadedFiles, UploadFile

__all__ = [
    "AgentEndpointDef",
    "AgentResponse",
    "AgentTasks",
    "FileResult",
    "HTMLResult",
    "HtmxHeaders",
    "Intent",
    "IntentAction",
    "IntentParser",
    "IntentScope",
    "PlainTextResult",
    "ResponseFormatter",
    "Session",
    "SessionManager",
    "UploadFile",
    "UploadedFiles",
]
