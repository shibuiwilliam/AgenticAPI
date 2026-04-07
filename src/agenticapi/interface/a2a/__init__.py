"""Agent-to-Agent communication protocol."""

from __future__ import annotations

from agenticapi.interface.a2a.capability import Capability, CapabilityRegistry
from agenticapi.interface.a2a.protocol import A2AMessage, A2AMessageType, A2ARequest, A2AResponse
from agenticapi.interface.a2a.trust import TrustPolicy, TrustScorer

__all__ = [
    "A2AMessage",
    "A2AMessageType",
    "A2ARequest",
    "A2AResponse",
    "Capability",
    "CapabilityRegistry",
    "TrustPolicy",
    "TrustScorer",
]
