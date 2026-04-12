"""Live-escalation autonomy policy (Phase F6).

Why a live policy, not a static ``autonomy_level`` string.

    Before F6, every endpoint declared its autonomy as a fixed string
    — ``"auto"`` / ``"supervised"`` / ``"manual"``. That's the right
    default for a predictable API surface, but real agents encounter
    live signals *during* execution that should change the rules:

    * The LLM returns a low-confidence plan
    * The cost-so-far on this request crosses a budget threshold
    * A :class:`~agenticapi.harness.policy.base.Policy` flags a risky
      operation
    * The intent domain lands in previously-unseen territory
      (a novelty score)

    Each of those should be able to *escalate* the autonomy level
    mid-request. ``AutonomyPolicy`` is the declarative mechanism that
    makes it happen.

Design principles.

    * **Monotonic** — escalations only get stricter, never looser.
      Once a request has been escalated to ``supervised`` it cannot
      fall back to ``auto`` even if later signals say otherwise. This
      is the whole point of the safety property: a risky moment in
      the request *taints* the rest of it.
    * **Declarative** — rules are plain data (``EscalateWhen``),
      evaluated in order, the first match wins per signal type.
      Handlers never write if/else trees to decide the level.
    * **Observable** — every escalation emits an
      :class:`~agenticapi.interface.stream.AutonomyChangedEvent` on
      the stream, which lands in the audit trace and is visible to
      the client in real time. No silent level flips.
    * **Composable** — ``AutonomyPolicy`` lives in the harness policy
      package, alongside ``CodePolicy`` / ``BudgetPolicy`` / etc., so
      apps can mix it with the rest of the harness and the audit /
      OTEL substrate picks it up for free.

Lifecycle.

    1. Endpoint decorator: ``@app.agent_endpoint(autonomy=policy,
       streaming="sse")``.
    2. Framework builds an :class:`AutonomyState` per request,
       starting at ``policy.start``.
    3. Handler calls ``await stream.report_signal(confidence=0.6,
       cost_usd=0.02)`` (or the framework synthesises signals from
       LLM/tool call observations).
    4. Stream forwards the signal to its attached ``AutonomyState``,
       which evaluates the rules, determines whether to escalate, and
       — if so — emits an ``AutonomyChangedEvent`` and updates its
       internal level.
    5. Later rule checks (like approvals) consult
       ``stream.current_autonomy_level`` instead of the static
       endpoint string.

Relationship to ``autonomy_level``.

    The static ``autonomy_level`` field on :class:`AgentEndpointDef`
    stays as the fallback. When ``autonomy=`` is also set, it takes
    precedence and the start level comes from
    ``autonomy.start``. Endpoints without an :class:`AutonomyPolicy`
    behave exactly as they did before F6 — this is strictly additive.
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from agenticapi.types import AutonomyLevel

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Autonomy strictness ordering
# ---------------------------------------------------------------------------


_STRICTNESS: dict[AutonomyLevel, int] = {
    AutonomyLevel.AUTO: 0,
    AutonomyLevel.SUPERVISED: 1,
    AutonomyLevel.MANUAL: 2,
}


def _strictness(level: AutonomyLevel) -> int:
    """Integer strictness rank for an autonomy level. Higher = stricter."""
    return _STRICTNESS[level]


def _coerce_level(value: str | AutonomyLevel) -> AutonomyLevel:
    """Accept either the enum or the legacy string and return the enum."""
    if isinstance(value, AutonomyLevel):
        return value
    return AutonomyLevel(value)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class EscalateWhen(BaseModel):
    """A single escalation rule in an :class:`AutonomyPolicy`.

    A rule fires when **all** of its configured conditions are true
    for the reported signal. Unspecified conditions are ignored, so a
    rule with only ``confidence_below=0.7`` fires whenever a signal
    reports a confidence below 0.7 regardless of cost or other fields.

    Attributes:
        confidence_below: Fire when ``signal["confidence"]`` is below
            this value. ``None`` disables the check.
        cost_usd_above: Fire when the cumulative request cost (USD)
            exceeds this value. ``None`` disables the check.
        novelty_above: Fire when the novelty score for this signal is
            above this value. ``None`` disables the check.
        policy_flagged: Fire when *any* policy has flagged the request
            at evaluation time. Usually set by the harness after a
            policy warning/violation short of a full block.
        level: The level to escalate *to* when the rule fires. The
            actual level transition still respects monotonicity —
            a rule that would move the level *down* is ignored.
        reason: Human-readable reason for logs / audit / stream
            events. When omitted, a reason is synthesised from the
            triggering condition.
    """

    model_config = ConfigDict(extra="forbid")

    confidence_below: float | None = None
    cost_usd_above: float | None = None
    novelty_above: float | None = None
    policy_flagged: bool | None = None
    level: AutonomyLevel
    reason: str | None = None

    def matches(self, signal: AutonomySignal) -> bool:
        """Return ``True`` when this rule's conditions hold for ``signal``.

        A rule matches iff *every* configured condition is satisfied.
        An unconfigured condition (``None``) is a wildcard.
        """
        if self.confidence_below is not None and (
            signal.confidence is None or signal.confidence >= self.confidence_below
        ):
            return False
        if self.cost_usd_above is not None and (signal.cost_usd is None or signal.cost_usd <= self.cost_usd_above):
            return False
        if self.novelty_above is not None and (signal.novelty is None or signal.novelty <= self.novelty_above):
            return False
        # Check policy_flagged condition: if configured, signal must match.
        policy_flagged_mismatch = self.policy_flagged is not None and bool(signal.policy_flagged) != self.policy_flagged
        return not policy_flagged_mismatch

    def synthesised_reason(self, signal: AutonomySignal) -> str:
        """Best-effort human-readable reason for this rule firing."""
        if self.reason:
            return self.reason
        if self.confidence_below is not None and signal.confidence is not None:
            return f"confidence {signal.confidence:.2f} < {self.confidence_below}"
        if self.cost_usd_above is not None and signal.cost_usd is not None:
            return f"cost ${signal.cost_usd:.4f} > ${self.cost_usd_above}"
        if self.novelty_above is not None and signal.novelty is not None:
            return f"novelty {signal.novelty:.2f} > {self.novelty_above}"
        if self.policy_flagged:
            return "policy flagged"
        return "escalation rule matched"


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------


class AutonomySignal(BaseModel):
    """A live observation the harness / handler reports to the autonomy policy.

    Handlers report signals explicitly via ``stream.report_signal(...)``;
    the framework can also synthesise signals from internal observations
    (LLM confidence, cumulative cost, policy evaluation flags) so
    handlers rarely need to construct these by hand.

    Signals are plain data objects — no side effects. The decision to
    escalate lives in :meth:`AutonomyPolicy.resolve`.
    """

    model_config = ConfigDict(extra="forbid")

    confidence: float | None = None
    cost_usd: float | None = None
    novelty: float | None = None
    policy_flagged: bool = False
    note: str | None = None


# ---------------------------------------------------------------------------
# The policy itself
# ---------------------------------------------------------------------------


class AutonomyPolicy(BaseModel):
    """Declarative rule-driven autonomy policy (Phase F6).

    A live policy that maps reported :class:`AutonomySignal`s onto
    autonomy-level transitions. Compose with an
    :class:`~agenticapi.interface.stream.AgentStream` on a streaming
    endpoint and escalations show up as ``AutonomyChangedEvent``s in
    the wire format, in the audit trace, and in OTEL span events.

    Example:
        from agenticapi import AutonomyLevel, AutonomyPolicy, EscalateWhen

        policy = AutonomyPolicy(
            start=AutonomyLevel.AUTO,
            rules=[
                EscalateWhen(confidence_below=0.7, level=AutonomyLevel.SUPERVISED),
                EscalateWhen(cost_usd_above=0.20, level=AutonomyLevel.SUPERVISED),
                EscalateWhen(policy_flagged=True, level=AutonomyLevel.MANUAL),
            ],
        )

        @app.agent_endpoint(name="analytics", autonomy=policy, streaming="sse")
        async def analytics(intent, context, stream):
            await stream.report_signal(confidence=0.6)  # → SUPERVISED
            await stream.report_signal(cost_usd=0.25)   # → already SUPERVISED (no-op)
            await stream.report_signal(policy_flagged=True)  # → MANUAL
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    start: AutonomyLevel = AutonomyLevel.SUPERVISED
    rules: list[EscalateWhen] = Field(default_factory=list)

    def resolve(self, current: AutonomyLevel, signal: AutonomySignal) -> tuple[AutonomyLevel, EscalateWhen | None]:
        """Compute the next autonomy level for a reported signal.

        Iterates the rules in declaration order; the **strictest**
        matching rule wins. Monotonicity is enforced here: if the
        winning rule would move the level *down*, it's ignored and
        the current level is returned unchanged.

        Returns:
            ``(new_level, triggered_rule)``. ``triggered_rule`` is
            ``None`` when no rule matched or when the winning rule
            would have moved the level downward.
        """
        best: EscalateWhen | None = None
        for rule in self.rules:
            if not rule.matches(signal):
                continue
            if best is None or _strictness(rule.level) > _strictness(best.level):
                best = rule
        if best is None:
            return current, None
        if _strictness(best.level) <= _strictness(current):
            return current, None
        return best.level, best


# ---------------------------------------------------------------------------
# Live per-request state
# ---------------------------------------------------------------------------


class AutonomyState:
    """Mutable per-request wrapper around an :class:`AutonomyPolicy`.

    An :class:`AgentStream` owns one of these when the endpoint was
    registered with an ``autonomy=`` policy. The stream forwards
    reported signals to :meth:`observe`; the state updates its
    current level and — via the stream's emit channel — produces
    an ``AutonomyChangedEvent`` for each transition.

    The state is intentionally *not* a Pydantic model — we want
    mutable fields and an async emit hook, which Pydantic models
    make awkward. It's a small private class and never serialised
    directly (the event it emits is the thing that gets serialised).
    """

    __slots__ = ("_emit_change", "_policy", "current_level", "history")

    def __init__(
        self,
        *,
        policy: AutonomyPolicy,
        emit_change: _EmitChangeCallback | None = None,
    ) -> None:
        """Initialize the state.

        Args:
            policy: The declarative policy to evaluate signals against.
            emit_change: Optional async callback invoked when the
                level transitions. The :class:`AgentStream` passes one
                here so it can turn the transition into a typed event
                on the wire. ``None`` disables emission — useful in
                unit tests that want to inspect transitions directly.
        """
        self._policy = policy
        self._emit_change = emit_change
        self.current_level: AutonomyLevel = policy.start
        self.history: list[dict[str, Any]] = []

    @property
    def policy(self) -> AutonomyPolicy:
        return self._policy

    async def observe(self, signal: AutonomySignal) -> AutonomyLevel:
        """Feed a signal through the policy and apply any transition.

        Returns the current level after evaluation (which may or may
        not differ from the level before). When a transition happens,
        the ``emit_change`` callback is awaited so the stream can turn
        the transition into an ``AutonomyChangedEvent``.
        """
        previous = self.current_level
        next_level, rule = self._policy.resolve(previous, signal)
        if rule is None or next_level == previous:
            return previous
        self.current_level = next_level
        entry = {
            "previous": previous.value,
            "current": next_level.value,
            "reason": rule.synthesised_reason(signal),
            "signal": signal.model_dump(mode="json"),
        }
        self.history.append(entry)
        logger.info(
            "autonomy_escalated",
            previous=previous.value,
            current=next_level.value,
            reason=entry["reason"],
        )
        if self._emit_change is not None:
            await self._emit_change(
                previous=previous,
                current=next_level,
                reason=entry["reason"],
                signal=signal,
            )
        return next_level


# Type alias for the emit callback passed into AutonomyState.
# We declare it as an Any callable rather than a Protocol to keep
# the stream module's import lightweight and avoid a circular import.
_EmitChangeCallback = Any  # async (previous, current, reason, signal) -> None


__all__ = [
    "AutonomyLevel",
    "AutonomyPolicy",
    "AutonomySignal",
    "AutonomyState",
    "EscalateWhen",
]
