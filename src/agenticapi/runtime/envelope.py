"""MeshEnvelope — shared propagation primitive (PROJECT_ENHANCE §10).

Why a shared envelope matters.

    The three strategic elements proposed in ``PROJECT_ENHANCE.md``
    all carry the same metadata across execution boundaries:

    * **Element 1 (Mesh):** each ``ctx.call("role", payload)`` hop
      must propagate the trace lineage, the budget remaining, the
      approval ticket, and the autonomy posture.
    * **Element 2 (Trust):** the sandbox must receive the exact set
      of capabilities the caller declared, so the kernel can
      enforce them.
    * **Element 3 (Flywheel):** feedback joining needs to know
      which policies / budgets / caps were active when a trace
      was produced, so the model doesn't learn from mismatched
      contexts.

    Without a single envelope type, each element would reinvent its
    own propagation dict and the three tracks would diverge into
    incompatible shapes the moment any two are composed.

What this module ships.

    * :class:`MeshEnvelope` — a frozen, slotted dataclass carrying
      ``trace_id``, ``parent_trace_id``, ``depth``,
      ``budget_remaining_usd``, ``capabilities`` (forward-ref, wired
      in Element 2), ``approval_ticket``, ``autonomy_level``,
      ``origin``, and ``metadata``.
    * :meth:`MeshEnvelope.descend` — build a child envelope for a
      nested execution (Element 1) or sandbox invocation (Element 2).
    * :meth:`MeshEnvelope.to_row` — flatten to a JSON-serialisable
      dict for the audit store and OTEL span attributes.
    * :func:`mint_envelope` — convenience factory that builds a
      top-level envelope from a trace_id + optional budget + optional
      autonomy level, so ``app.py`` doesn't have to call the raw
      constructor.

What this module does *not* ship.

    Zero new behaviour. Every existing code path works exactly as
    before. The envelope is threaded through ``AgentContext``,
    ``HarnessEngine.execute``, ``HarnessEngine.call_tool``,
    ``ExecutionTrace``, and the OTEL span attribute helper, but
    all of those accept ``None`` as the default and do nothing
    different when ``None`` is passed. The three strategic elements
    will consume the non-None paths when they ship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MeshEnvelope:
    """Propagation envelope carried across every harness boundary.

    Every cross-boundary call — mesh hop (Element 1), sandbox
    execution (Element 2), feedback event (Element 3), resume
    endpoint (F5), replay (A6) — threads this envelope so
    downstream primitives (budget, audit, approval, autonomy,
    capabilities) see consistent lineage.

    The envelope is intentionally **frozen** so downstream stages
    cannot mutate it out from under the caller. The only way to
    build a child envelope is :meth:`descend`, which returns a
    new instance.

    Attributes:
        trace_id: W3C-compatible trace identifier (hex). Unique
            per top-level request; child envelopes get their own
            ``trace_id`` via :meth:`descend`.
        parent_trace_id: ``trace_id`` of the enclosing execution,
            when any. ``None`` for top-level requests.
        depth: Nesting depth. ``0`` for top-level requests; each
            :meth:`descend` increments by 1. Guards against
            recursive mesh calls (Element 1 can reject calls
            beyond a configured max depth).
        budget_remaining_usd: Current wallet remaining from the
            enclosing :class:`BudgetPolicy` scope, or ``None`` if
            uncapped. Updated by the mesh's budget-propagation
            helpers in Element 1.
        capabilities: Effective capability grant for this call.
            Populated starting in Element 2 (``Capabilities``
            type). Before Element 2 ships this is always ``None``.
        approval_ticket: Ancestor's in-flight approval id when
            the call is nested under an open
            :class:`ApprovalHandle`; ``None`` otherwise. Used by
            Element 1 for approval bubbling.
        autonomy_level: ``"auto"`` / ``"supervised"`` / ``"manual"``
            — the live level from :class:`AutonomyPolicy` at the
            moment the envelope was minted. Downstream calls
            inherit and can only tighten (monotonic).
        origin: What kind of boundary crossing this envelope
            represents: ``"request"`` (default top-level),
            ``"mesh"`` (Element 1 hop), ``"sandbox"`` (Element 2
            invocation), ``"replay"`` (A6 replay), ``"feedback"``
            (Element 3 feedback event).
        metadata: Free-form propagation dict for custom pipeline
            stages. Stored as JSON in the audit row.
    """

    trace_id: str
    parent_trace_id: str | None = None
    depth: int = 0
    budget_remaining_usd: float | None = None
    capabilities: Any | None = None  # Element 2 will narrow to Capabilities
    approval_ticket: str | None = None
    autonomy_level: str = "auto"
    origin: str = "request"
    metadata: dict[str, Any] = field(default_factory=dict)

    def descend(self, *, new_trace_id: str, origin: str = "mesh") -> MeshEnvelope:
        """Return a child envelope for a nested execution.

        Used by Element 1 (Mesh): every ``ctx.call(role, payload)``
        descends the parent envelope so the child inherits budget,
        capabilities, and autonomy, but gets its own ``trace_id``
        and incremented ``depth``.

        Args:
            new_trace_id: The child execution's unique identifier.
            origin: What this child execution represents. Usually
                ``"mesh"``; Element 2 may use ``"sandbox"``.

        Returns:
            A new :class:`MeshEnvelope` instance with
            ``parent_trace_id`` set to the caller's ``trace_id``
            and ``depth`` incremented by 1.
        """
        return MeshEnvelope(
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            depth=self.depth + 1,
            budget_remaining_usd=self.budget_remaining_usd,
            capabilities=self.capabilities,
            approval_ticket=self.approval_ticket,
            autonomy_level=self.autonomy_level,
            origin=origin,
            metadata=dict(self.metadata),
        )

    def to_row(self) -> dict[str, Any]:
        """Flatten to a JSON-serialisable dict for the audit store.

        The returned dict is what ``ExecutionTrace.envelope`` stores
        so a later join (Element 3's ``ExperienceStore``) can filter
        traces by lineage, budget posture, or capability grant
        without parsing the full trace row.
        """
        return {
            "trace_id": self.trace_id,
            "parent_trace_id": self.parent_trace_id,
            "depth": self.depth,
            "budget_remaining_usd": self.budget_remaining_usd,
            "approval_ticket": self.approval_ticket,
            "autonomy_level": self.autonomy_level,
            "origin": self.origin,
            "metadata": self.metadata,
        }


def mint_envelope(
    *,
    trace_id: str,
    budget_remaining_usd: float | None = None,
    autonomy_level: str = "auto",
    origin: str = "request",
) -> MeshEnvelope:
    """Convenience factory for building a top-level envelope.

    Called by ``AgenticApp`` at the start of every request so the
    harness always has an envelope to thread through its pipeline.
    The factory avoids repeating default values and gives a clean
    call site in ``app.py``.

    Returns:
        A fresh :class:`MeshEnvelope` with ``depth=0``,
        ``parent_trace_id=None``, and all other fields at their
        defaults.
    """
    return MeshEnvelope(
        trace_id=trace_id,
        budget_remaining_usd=budget_remaining_usd,
        autonomy_level=autonomy_level,
        origin=origin,
    )


__all__ = [
    "MeshEnvelope",
    "mint_envelope",
]
