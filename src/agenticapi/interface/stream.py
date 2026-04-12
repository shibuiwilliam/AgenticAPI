"""Streaming agent lifecycle (Phase F1).

This module implements the **typed event schema** and the
:class:`AgentStream` handler-side helper that together let an agent
endpoint emit reasoning, tool calls, partial results, and approval
requests as they happen — instead of buffering everything until the
handler returns.

Why a typed event schema (not raw strings).

    Every emitted event is a Pydantic model. That means:

    * Each event carries a stable JSON shape downstream consumers
      (browsers, CLIs, mobile apps, audit pipelines) can rely on.
    * The `seq` and `timestamp` fields are computed by the framework,
      not the handler — clients can re-order out-of-order events and
      detect drops.
    * The audit trace records the *typed* event, so a streaming
      request produces the same shape of trace as a non-streaming
      one — only with extra detail.
    * The OpenTelemetry span events for streaming requests use the
      same field names and types as the wire format, so APMs see
      one consistent vocabulary.

What the handler interacts with.

    Handlers declare an :class:`AgentStream` parameter and call
    ``await stream.emit_thought(...)``, ``stream.emit_tool_call_started(...)``,
    ``stream.emit_partial(...)``, ``stream.emit_final(...)``, or
    ``stream.request_approval(...)``. The framework wires every
    method up to:

    1. The transport (SSE in F2, NDJSON in F3, WebSocket in F4 — all
       follow-on tasks). Each event is rendered into the wire format
       and pushed to the client.
    2. The audit recorder (F8). Every event is appended to the
       :attr:`ExecutionTrace.stream_events` list.
    3. The OTel tracer. When tracing is configured, each event becomes
       a span event under the request's root span.

    The handler never has to think about any of those — they all just
    happen.

Why ``request_approval`` lives here too (not in F5 only).

    The :meth:`AgentStream.request_approval` API surface is defined as
    part of F1 so the event schema and the in-signature shape stay
    consistent. F5 lands the *runtime* — the resume endpoint, the
    asyncio.Event-based wait, the timeout modes — but the API method
    on :class:`AgentStream` is part of the F1 contract.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from agenticapi.harness.policy.autonomy_policy import (
        AutonomyLevel,
        AutonomyPolicy,
        AutonomySignal,
        AutonomyState,
    )
    from agenticapi.interface.stream_store import StreamStore

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Event schema
# ---------------------------------------------------------------------------


class AgentEvent(BaseModel):
    """Base class for every streamable agent lifecycle event.

    Concrete subclasses set ``kind`` to a fixed string literal so the
    wire format is self-describing. The framework computes ``seq`` and
    ``timestamp`` automatically — handlers never set them.

    Attributes:
        kind: The discriminator string. Set by every concrete subclass.
        seq: Monotonic sequence number assigned by :class:`AgentStream`.
            Clients use this to detect dropped or re-ordered events.
        timestamp: ISO-8601 wall-clock timestamp at emission time.
            Always UTC.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    seq: int = 0
    timestamp: str = ""


class ThoughtEvent(AgentEvent):
    """A piece of free-form reasoning text from the agent.

    Used for chain-of-thought emission. Each emit is one chunk; the
    client typically renders them as the agent "thinks" out loud.
    """

    kind: str = "thought"
    text: str
    confidence: float | None = None


class ToolCallStartedEvent(AgentEvent):
    """The agent is about to invoke a tool.

    Emitted *before* the call so the client can show a "calling tool…"
    spinner. The matching :class:`ToolCallCompletedEvent` references the
    same ``call_id``.
    """

    kind: str = "tool_call_started"
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallCompletedEvent(AgentEvent):
    """A previously started tool call has completed.

    The client matches this against the prior
    :class:`ToolCallStartedEvent` by ``call_id``.
    """

    kind: str = "tool_call_completed"
    call_id: str
    is_error: bool = False
    result_summary: str | None = None
    duration_ms: float | None = None


class PartialResultEvent(AgentEvent):
    """A partial output the client should append to the in-progress result.

    Useful for streaming a long answer chunk-by-chunk, or emitting
    rows from a query as they're produced. The ``chunk`` payload is
    intentionally untyped (``Any``) — handlers can stream strings,
    dicts, or any JSON-serialisable value.
    """

    kind: str = "partial_result"
    chunk: Any
    is_last: bool = False


class ApprovalRequestedEvent(AgentEvent):
    """The agent has paused mid-execution and is asking the user a question.

    Carries enough information for a client UI to show a modal:
    the prompt, the available choices, and a deadline after which
    the framework's timeout-mode logic kicks in. The client responds
    by POSTing the chosen option to
    ``/agent/{name}/resume/{stream_id}``.
    """

    kind: str = "approval_requested"
    approval_id: str
    stream_id: str
    prompt: str
    options: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = None


class ApprovalResolvedEvent(AgentEvent):
    """The user has answered an :class:`ApprovalRequestedEvent`.

    Emitted after the framework receives a resume call (or after the
    timeout fires and the configured timeout-mode produces an answer).
    """

    kind: str = "approval_resolved"
    approval_id: str
    decision: str
    timed_out: bool = False


class FinalEvent(AgentEvent):
    """Terminal success event carrying the handler's final return value.

    The framework synthesises this automatically from whatever the
    handler ``return``s after the stream closes — handlers do not
    usually emit it explicitly.
    """

    kind: str = "final"
    result: Any = None


class ErrorEvent(AgentEvent):
    """Terminal error event.

    Emitted when the handler raises an unhandled exception or when
    the framework deems the stream broken (e.g. an approval timed out
    in ``reject`` mode).
    """

    kind: str = "error"
    error_kind: str
    message: str


class AutonomyChangedEvent(AgentEvent):
    """The autonomy level for this request just escalated (Phase F6).

    Emitted by :class:`AgentStream` whenever a reported signal causes
    an :class:`~agenticapi.harness.policy.autonomy_policy.AutonomyPolicy`
    to escalate the live level. Escalations are monotonic — the level
    only ever gets *stricter* — so clients can render a clear "this
    request is now in supervised mode" banner without worrying about
    bouncing.

    Attributes:
        previous: The level before this transition.
        current: The new level after this transition.
        reason: Human-readable explanation for why the transition
            fired — either the rule's configured ``reason`` string or
            a best-effort one synthesised from the triggering
            condition ("confidence 0.62 < 0.70", etc.).
        signal: The raw :class:`AutonomySignal` that caused the
            transition, rendered as a plain JSON-serialisable dict.
    """

    kind: str = "autonomy_changed"
    previous: str
    current: str
    reason: str
    signal: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# AgentStream — handler-facing helper
# ---------------------------------------------------------------------------


class AgentStream:
    """Handler-side helper for emitting streaming agent events.

    A new :class:`AgentStream` is created per request and injected
    into the handler when the handler declares an ``AgentStream``
    parameter. The framework consumes the stream's internal queue
    and pushes events through whichever transport (SSE / NDJSON /
    WebSocket) was configured on the endpoint.

    Example:
        @app.agent_endpoint(name="analytics", streaming="sse")
        async def analytics(intent, stream: AgentStream) -> Report:
            await stream.emit_thought("Reading schema…")
            schema = await load_schema()

            await stream.emit_thought("Generating query…")
            plan = await llm.plan(intent.params, schema=schema)

            if plan.estimated_rows > 1_000_000:
                decision = await stream.request_approval(
                    prompt=f"~{plan.estimated_rows:,} rows. Proceed?",
                    options=["yes", "no", "add-limit"],
                    timeout_seconds=300,
                )
                if decision == "no":
                    raise UserCancelled()

            async for row in db.stream(plan.sql):
                await stream.emit_partial(row)

            return Report(rows=...)
    """

    def __init__(
        self,
        *,
        stream_id: str,
        approval_handle_factory: Callable[[str], ApprovalHandle] | None = None,
        autonomy: AutonomyPolicy | None = None,
        stream_store: StreamStore | None = None,
    ) -> None:
        """Initialize the stream.

        Args:
            stream_id: Unique identifier for this streaming request.
                Embedded in every :class:`ApprovalRequestedEvent` so
                the resume endpoint can route the response back to
                this exact handler.
            approval_handle_factory: Optional factory used by F5 to
                build resumable approval handles. When ``None``,
                ``request_approval`` raises :class:`NotImplementedError`
                so callers don't silently hang.
            autonomy: Optional :class:`AutonomyPolicy` (Phase F6) that
                the stream should consult whenever the handler reports
                a live signal via :meth:`report_signal`. When set,
                each escalation produces an :class:`AutonomyChangedEvent`
                on the wire + in the audit trace. ``None`` disables
                live escalation — the stream still exposes a
                :attr:`current_autonomy_level` property that returns
                :attr:`AutonomyLevel.AUTO` as a neutral default.
            stream_store: Optional :class:`StreamStore` (Phase F7) for
                persisting the event log so clients can reconnect
                mid-stream. Every emitted event is forwarded to the
                store so the resume route can replay the log. When
                ``None``, the stream behaves as before (F2 / F3) —
                events only live on the live queue.
        """
        self.stream_id = stream_id
        self._queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._closed = False
        self._seq_counter = count()
        self._emitted: list[AgentEvent] = []
        self._approval_handle_factory = approval_handle_factory
        self._stream_store: StreamStore | None = stream_store
        # Autonomy state (F6). Built lazily so imports stay cheap and
        # the stream module doesn't pull in harness.policy eagerly.
        self._autonomy_state: AutonomyState | None = None
        if autonomy is not None:
            from agenticapi.harness.policy.autonomy_policy import AutonomyState

            self._autonomy_state = AutonomyState(
                policy=autonomy,
                emit_change=self._emit_autonomy_change,
            )

    # ------------------------------------------------------------------
    # Public emit methods
    # ------------------------------------------------------------------

    async def emit_thought(self, text: str, *, confidence: float | None = None) -> None:
        """Emit a chain-of-thought chunk."""
        await self._emit(ThoughtEvent(text=text, confidence=confidence))

    async def emit_tool_call_started(
        self,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        """Announce the start of a tool invocation."""
        await self._emit(ToolCallStartedEvent(call_id=call_id, name=name, arguments=arguments or {}))

    async def emit_tool_call_completed(
        self,
        *,
        call_id: str,
        is_error: bool = False,
        result_summary: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Announce a tool invocation has finished."""
        await self._emit(
            ToolCallCompletedEvent(
                call_id=call_id,
                is_error=is_error,
                result_summary=result_summary,
                duration_ms=duration_ms,
            )
        )

    async def emit_partial(self, chunk: Any, *, is_last: bool = False) -> None:
        """Emit a partial result chunk to be appended on the client side."""
        await self._emit(PartialResultEvent(chunk=chunk, is_last=is_last))

    async def emit_final(self, result: Any) -> None:
        """Emit the terminal :class:`FinalEvent` for this stream.

        The framework calls this automatically with the handler's
        return value, so handlers usually don't need to call it. It's
        public for unusual flows that want to terminate streaming
        early without raising.
        """
        await self._emit(FinalEvent(result=result))
        await self.close()

    async def emit_error(self, *, error_kind: str, message: str) -> None:
        """Emit a terminal :class:`ErrorEvent`."""
        await self._emit(ErrorEvent(error_kind=error_kind, message=message))
        await self.close()

    # ------------------------------------------------------------------
    # Autonomy escalation (F6)
    # ------------------------------------------------------------------

    async def report_signal(
        self,
        *,
        confidence: float | None = None,
        cost_usd: float | None = None,
        novelty: float | None = None,
        policy_flagged: bool = False,
        note: str | None = None,
    ) -> str:
        """Report a live signal to the attached :class:`AutonomyPolicy`.

        Handlers call this whenever a live observation might affect
        the autonomy posture — e.g. after an LLM call returns a
        confidence score, after a budgeted operation adds to the
        cumulative cost, or after a policy evaluator flags a risky
        operation. The framework can also synthesise signals from
        internal observations on the handler's behalf.

        Returns the current :class:`AutonomyLevel` *after* the signal
        is resolved, as its string value (so handlers can write
        ``if await stream.report_signal(...) == "manual"``). When no
        autonomy policy is attached the current level is always
        ``"auto"`` (a neutral default — the policy is what gives
        ``auto`` teeth).
        """
        from agenticapi.harness.policy.autonomy_policy import AutonomySignal

        if self._autonomy_state is None:
            return "auto"
        signal = AutonomySignal(
            confidence=confidence,
            cost_usd=cost_usd,
            novelty=novelty,
            policy_flagged=policy_flagged,
            note=note,
        )
        level = await self._autonomy_state.observe(signal)
        return level.value

    @property
    def current_autonomy_level(self) -> str:
        """Current autonomy level as a string.

        Returns ``"auto"`` when no policy is attached so callers can
        always read it safely; when a policy is attached it reflects
        the live (post-escalation) level.
        """
        if self._autonomy_state is None:
            return "auto"
        return self._autonomy_state.current_level.value

    @property
    def autonomy_history(self) -> list[dict[str, Any]]:
        """Ordered list of autonomy transitions for this request.

        Empty when no policy is attached or no escalations have
        fired. Used by the audit integration (F8) so downstream
        consumers can reconstruct the escalation trail.
        """
        if self._autonomy_state is None:
            return []
        return list(self._autonomy_state.history)

    async def _emit_autonomy_change(
        self,
        *,
        previous: AutonomyLevel,
        current: AutonomyLevel,
        reason: str,
        signal: AutonomySignal,
    ) -> None:
        """Callback :class:`AutonomyState` uses to turn a transition into an event."""
        await self._emit(
            AutonomyChangedEvent(
                previous=previous.value,
                current=current.value,
                reason=reason,
                signal=signal.model_dump(mode="json"),
            )
        )

    # ------------------------------------------------------------------
    # In-request human-in-the-loop (F5 hook)
    # ------------------------------------------------------------------

    async def request_approval(
        self,
        *,
        prompt: str,
        options: list[str] | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        """Pause the handler and ask the user a question.

        Emits an :class:`ApprovalRequestedEvent` immediately, then
        suspends until the framework's resume endpoint receives a
        decision (or the timeout fires). Returns the user's chosen
        option, or — when the timeout-mode resolves to a default —
        whichever default the framework's :class:`AutonomyPolicy` /
        timeout configuration produced.

        The actual suspend/resume mechanics live in F5
        (:func:`agenticapi.interface.stream.create_approval_handle`).
        F1 ships only the API surface; calling ``request_approval`` on
        a stream that wasn't built with an approval factory raises
        :class:`NotImplementedError` rather than hanging silently.
        """
        if self._approval_handle_factory is None:
            raise NotImplementedError(
                "request_approval() called on a stream that has no "
                "approval handle factory. The endpoint must be created "
                "with streaming enabled and the F5 resume registry wired up."
            )

        handle = self._approval_handle_factory(self.stream_id)
        await self._emit(
            ApprovalRequestedEvent(
                approval_id=handle.approval_id,
                stream_id=self.stream_id,
                prompt=prompt,
                options=list(options or []),
                timeout_seconds=timeout_seconds,
            )
        )
        decision, timed_out = await handle.wait(timeout_seconds=timeout_seconds)
        await self._emit(
            ApprovalResolvedEvent(
                approval_id=handle.approval_id,
                decision=decision,
                timed_out=timed_out,
            )
        )
        return decision

    # ------------------------------------------------------------------
    # Framework-facing helpers (transports + audit consume these)
    # ------------------------------------------------------------------

    async def consume(self) -> AsyncIterator[AgentEvent]:
        """Yield events from the internal queue until the stream closes.

        Used by the SSE / NDJSON / WebSocket transports. The transport
        loop awaits this iterator and pushes each event to the wire.
        """
        while True:
            if self._closed and self._queue.empty():
                return
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                if self._closed:
                    return
                continue
            yield event

    async def close(self) -> None:
        """Mark the stream closed.

        After ``close()`` returns, ``consume()`` drains any remaining
        events and exits. Idempotent — safe to call multiple times.
        If a stream store (F7) is attached, also marks the stored
        event log complete so tailing consumers can exit cleanly.
        """
        already_closed = self._closed
        self._closed = True
        if not already_closed and self._stream_store is not None:
            try:
                await self._stream_store.mark_complete(self.stream_id)
            except Exception:
                logger.exception("stream_store_mark_complete_failed", stream_id=self.stream_id)

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def emitted_events(self) -> list[AgentEvent]:
        """Snapshot of every event emitted on this stream so far.

        Used by F8 (audit integration) to attach the event log to the
        request's :class:`ExecutionTrace`. Tests also use it to make
        assertions without going through a transport.
        """
        return list(self._emitted)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _emit(self, event: AgentEvent) -> None:
        """Stamp seq/timestamp on an event, push it to the queue, persist it."""
        if self._closed:
            logger.warning(
                "agent_stream_emit_after_close",
                stream_id=self.stream_id,
                kind=event.kind,
            )
            return
        # Pydantic models are immutable by default if frozen, but ours
        # aren't — we mutate seq/timestamp in place at emission time.
        event.seq = next(self._seq_counter)
        event.timestamp = datetime.now(tz=UTC).isoformat()
        self._emitted.append(event)
        await self._queue.put(event)
        # Phase F7: persist to the stream store so reconnects can
        # replay the event log from the last seen seq. Append errors
        # are logged but never allowed to break the live request.
        if self._stream_store is not None:
            try:
                await self._stream_store.append(self.stream_id, event.model_dump(mode="json"))
            except Exception:
                logger.exception(
                    "stream_store_append_failed",
                    stream_id=self.stream_id,
                    kind=event.kind,
                )


# ---------------------------------------------------------------------------
# Approval handle protocol (F5 fills this in)
# ---------------------------------------------------------------------------


class ApprovalHandle:
    """A pending approval request that can be resolved by the resume endpoint.

    F1 ships the **interface**; F5 ships the **registry** that maps
    ``approval_id`` to live handles and the resume endpoint that fires
    :meth:`resolve`.

    The default :meth:`wait` implementation uses an :class:`asyncio.Event`
    so it composes cleanly with the framework's existing async
    machinery.
    """

    def __init__(self, *, approval_id: str, default_decision: str = "reject") -> None:
        self.approval_id = approval_id
        self._default_decision = default_decision
        self._event = asyncio.Event()
        self._decision: str | None = None
        self._timed_out = False

    def resolve(self, decision: str) -> None:
        """Called by the resume endpoint to wake the suspended handler."""
        if self._decision is not None:
            return  # idempotent — repeated resumes ignored
        self._decision = decision
        self._event.set()

    async def wait(self, *, timeout_seconds: float | None) -> tuple[str, bool]:
        """Suspend until the user resolves the approval or the timeout fires.

        Returns a (decision, timed_out) tuple. The default decision
        used on timeout matches the configured timeout-mode (see F5).
        """
        if timeout_seconds is None:
            await self._event.wait()
            assert self._decision is not None  # set by resolve()
            return (self._decision, False)
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout_seconds)
            assert self._decision is not None
            return (self._decision, False)
        except TimeoutError:
            self._timed_out = True
            return (self._default_decision, True)


ApprovalHandleFactoryType = Callable[[str], ApprovalHandle]
"""Type alias used by AgentStream.

A factory takes a ``stream_id`` and returns a fresh
:class:`ApprovalHandle` registered with whichever resume registry
the framework has wired up.
"""


def _wall_clock_ms() -> float:
    """Helper for transports to compute heartbeat intervals."""
    return time.monotonic() * 1000.0


__all__ = [
    "AgentEvent",
    "AgentStream",
    "ApprovalHandle",
    "ApprovalHandleFactoryType",
    "ApprovalRequestedEvent",
    "ApprovalResolvedEvent",
    "AutonomyChangedEvent",
    "ErrorEvent",
    "FinalEvent",
    "PartialResultEvent",
    "ThoughtEvent",
    "ToolCallCompletedEvent",
    "ToolCallStartedEvent",
]
