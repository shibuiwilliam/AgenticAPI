"""Multi-agent mesh orchestration (Element 2).

Provides ``AgentMesh`` for composing multiple agent roles into
orchestrated pipelines with budget propagation, trace linkage,
and cycle detection.
"""

from __future__ import annotations

from agenticapi.mesh.context import MeshContext
from agenticapi.mesh.mesh import AgentMesh

__all__ = [
    "AgentMesh",
    "MeshContext",
]
