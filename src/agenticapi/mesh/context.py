"""Request-scoped mesh context for inter-agent calls.

``MeshContext`` is the handler-facing API for invoking other roles
within the same ``AgentMesh``. It propagates the parent request's
budget scope and trace lineage so sub-agent calls debit the same
budget and appear as child spans.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from agenticapi.exceptions import AgenticAPIError

logger = structlog.get_logger(__name__)


class MeshCycleError(AgenticAPIError):
    """Raised when a cycle is detected in the mesh call graph."""

    def __init__(self, role: str, call_stack: list[str]) -> None:
        path = " -> ".join([*call_stack, role])
        super().__init__(f"Cycle detected in mesh: {path}")


@dataclass(slots=True)
class MeshContext:
    """Request-scoped context for inter-agent calls.

    Created per-request by the mesh and injected into orchestrator
    handlers. Provides ``call()`` for invoking other roles.

    Attributes:
        mesh: The parent ``AgentMesh`` instance.
        trace_id: The parent request's trace id.
        parent_budget_remaining_usd: Remaining budget from the parent
            request, if any. ``None`` means unbounded.
        call_stack: Ordered list of role names in the current call
            chain, used for cycle detection.
        spent_usd: Accumulated cost across all sub-calls.
    """

    mesh: Any  # AgentMesh — forward reference to avoid circular import
    trace_id: str = ""
    parent_budget_remaining_usd: float | None = None
    call_stack: list[str] = field(default_factory=list)
    spent_usd: float = 0.0

    async def call(self, role: str, payload: Any) -> Any:
        """Invoke a named role within the mesh.

        Performs cycle detection, budget enforcement, and trace
        propagation before delegating to the role's handler.

        Args:
            role: The name of the role to invoke.
            payload: The intent payload (string or dict) to pass.

        Returns:
            The role handler's return value.

        Raises:
            ValueError: If the role is not registered.
            MeshCycleError: If a call cycle is detected.
            agenticapi.exceptions.BudgetExceeded: If the budget is
                exhausted.
        """
        from agenticapi.mesh.mesh import AgentMesh  # noqa: TC001

        mesh: AgentMesh = self.mesh

        if role not in mesh._roles:
            msg = f"Unknown mesh role: '{role}'. Available: {sorted(mesh._roles)}"
            raise ValueError(msg)

        # Cycle detection.
        if role in self.call_stack:
            raise MeshCycleError(role, list(self.call_stack))

        # Budget check.
        if self.parent_budget_remaining_usd is not None and self.parent_budget_remaining_usd <= 0:
            from agenticapi.exceptions import BudgetExceeded

            raise BudgetExceeded(
                scope="mesh",
                limit_usd=0.0,
                observed_usd=self.spent_usd,
                violation="Mesh budget exhausted across sub-agent calls",
            )

        child_stack = [*self.call_stack, role]
        child_trace = f"{self.trace_id}:{role}:{uuid.uuid4().hex[:8]}"

        logger.info(
            "mesh_call",
            role=role,
            depth=len(child_stack),
            trace_id=child_trace,
        )

        handler = mesh._roles[role]

        # Build a child MeshContext for nested calls.
        child_ctx = MeshContext(
            mesh=mesh,
            trace_id=child_trace,
            parent_budget_remaining_usd=self.parent_budget_remaining_usd,
            call_stack=child_stack,
            spent_usd=self.spent_usd,
        )

        result = await handler(payload, child_ctx)

        logger.info(
            "mesh_call_complete",
            role=role,
            depth=len(child_stack),
            trace_id=child_trace,
        )

        return result
