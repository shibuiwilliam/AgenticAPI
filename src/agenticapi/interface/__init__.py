"""Interface layer for AgenticAPI.

The interface layer handles incoming requests, converting them into
structured Intent objects and returning formatted AgentResponse objects.

Re-exports key types for convenient access.
"""

from __future__ import annotations

from agenticapi.interface.endpoint import AgentEndpointDef
from agenticapi.interface.intent import Intent, IntentAction, IntentParser, IntentScope
from agenticapi.interface.response import AgentResponse, ResponseFormatter
from agenticapi.interface.session import Session, SessionManager

__all__ = [
    "AgentEndpointDef",
    "AgentResponse",
    "Intent",
    "IntentAction",
    "IntentParser",
    "IntentScope",
    "ResponseFormatter",
    "Session",
    "SessionManager",
]
