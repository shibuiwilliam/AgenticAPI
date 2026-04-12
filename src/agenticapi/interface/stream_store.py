"""Persistent stream-event log for resumable streams (Phase F7).

Why resumable streams matter.

    Real clients disconnect. Mobile networks drop. Laptops close
    lids. A streaming agent endpoint that resets its whole lifecycle
    every time the TCP connection wobbles is unusable for anything
    longer than a few seconds. The fix is to **decouple the handler
    from the connection**: the handler runs to completion on the
    server regardless of whether any client is watching, and the
    client can reconnect at any time and pick up the event log from
    whatever ``seq`` it had already consumed.

What this module ships.

    * :class:`StreamStore` — a small async protocol with ``append``,
      ``get_after``, ``wait``, ``mark_complete``, ``is_complete``.
    * :class:`InMemoryStreamStore` — the default implementation. A
      dict of ``stream_id → list[event dict]`` guarded by an
      :class:`asyncio.Lock`, plus a condition variable per stream so
      tailing consumers can wait efficiently for new events.
    * :func:`tail_from` — async iterator that consumers (the
      ``GET /agent/{name}/stream/{stream_id}`` resume route) use to
      replay-then-tail. Handles completion cleanly and terminates
      when the stream is marked done.

What's out of scope (for F7 specifically).

    * **Mid-handler resume.** Reviving a handler that stopped mid-
      execution (because the process restarted or the handler was
      garbage-collected) is a Phase G R&D topic — it needs handler
      serialisation, which is fundamentally harder than event-log
      persistence. F7's contract is strictly that the **event log**
      survives the disconnect; the handler still has to live on the
      original server process.
    * **Multi-host coordination.** The default in-memory store
      obviously can't be shared across hosts. A Redis-backed store
      can be swapped in via the same :class:`StreamStore` protocol
      and pairs with the same approach F5 takes for the approval
      registry.

Relationship to the audit store.

    The audit store (:class:`~agenticapi.harness.audit.recorder.AuditRecorder`)
    records the **final, closed** event log after the terminal
    :class:`FinalEvent`. The stream store is the *live* mirror used
    for reconnects — it churns during the request and is cleared
    after a TTL. Using the audit store for resume would work but be
    awkward because audit records are meant to be finalised snapshots,
    not live buffers.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agenticapi.interface.stream import AgentEvent

logger = structlog.get_logger(__name__)


@runtime_checkable
class StreamStore(Protocol):
    """Protocol for persistent stream-event logs.

    Implementations **must** be safe under concurrent append + read
    across asyncio tasks. The default :class:`InMemoryStreamStore`
    uses an ``asyncio.Lock`` and per-stream
    :class:`asyncio.Condition` to implement both.

    All methods are async so multi-host implementations (Redis,
    Postgres) can drop into the same protocol without restructuring
    the callers.
    """

    async def append(self, stream_id: str, event: dict[str, Any]) -> None:
        """Persist an event for ``stream_id``.

        Events must be appended in their emission order. The store
        uses ``event["seq"]`` as the ordering key so downstream
        consumers can request ranges by sequence.
        """
        ...

    async def get_after(self, stream_id: str, since_seq: int) -> list[dict[str, Any]]:
        """Return a snapshot of every stored event with ``seq > since_seq``.

        The returned list is a copy — callers can mutate it freely.
        """
        ...

    async def wait(self, stream_id: str, *, timeout: float) -> None:
        """Block until a new event is appended or ``timeout`` elapses.

        Returns without error on both the notification and the
        timeout paths — callers re-check ``get_after`` after the
        wait to decide whether anything new arrived.
        """
        ...

    async def mark_complete(self, stream_id: str) -> None:
        """Mark a stream as terminated.

        After this call, :meth:`is_complete` returns ``True`` and any
        pending :meth:`wait` calls wake immediately so consumers can
        exit the tailing loop.
        """
        ...

    async def is_complete(self, stream_id: str) -> bool:
        """Whether the stream has been marked complete."""
        ...

    async def discard(self, stream_id: str) -> None:
        """Drop everything stored for ``stream_id``.

        Called when a stream's TTL expires or when the caller wants
        to free the resources (e.g. after a successful audit record).
        """
        ...


class InMemoryStreamStore:
    """In-process stream store backed by an asyncio-locked dict.

    Suitable for single-host deployments and tests. Supports append,
    range read, condition-variable-based tailing, and explicit
    completion marking.

    The store holds one entry per stream:

    * ``events`` — the ordered list of emitted event dicts
    * ``complete`` — whether :meth:`mark_complete` has been called
    * ``condition`` — per-stream ``asyncio.Condition`` used by
      :meth:`wait` to block until a new append happens

    Notes:
        Each stream has its own condition (rather than a single
        global one) so a busy stream doesn't wake up tailers for
        unrelated streams. The outer ``_lock`` guards the ``_streams``
        dict itself; per-stream conditions have their own internal
        lock.
    """

    def __init__(self) -> None:
        self._streams: dict[str, _StreamEntry] = {}
        self._lock = asyncio.Lock()

    async def _entry(self, stream_id: str) -> _StreamEntry:
        """Look up (or create) the entry for ``stream_id``."""
        async with self._lock:
            entry = self._streams.get(stream_id)
            if entry is None:
                entry = _StreamEntry()
                self._streams[stream_id] = entry
            return entry

    async def append(self, stream_id: str, event: dict[str, Any]) -> None:
        entry = await self._entry(stream_id)
        async with entry.condition:
            entry.events.append(event)
            entry.condition.notify_all()

    async def get_after(self, stream_id: str, since_seq: int) -> list[dict[str, Any]]:
        entry = await self._entry(stream_id)
        async with entry.condition:
            return [e for e in entry.events if int(e.get("seq", -1)) > since_seq]

    async def wait(self, stream_id: str, *, timeout: float) -> None:
        entry = await self._entry(stream_id)
        async with entry.condition:
            if entry.complete:
                return
            try:
                await asyncio.wait_for(entry.condition.wait(), timeout=timeout)
            except TimeoutError:
                return

    async def mark_complete(self, stream_id: str) -> None:
        entry = await self._entry(stream_id)
        async with entry.condition:
            entry.complete = True
            entry.condition.notify_all()

    async def is_complete(self, stream_id: str) -> bool:
        async with self._lock:
            entry = self._streams.get(stream_id)
            if entry is None:
                return False
        async with entry.condition:
            return entry.complete

    async def discard(self, stream_id: str) -> None:
        async with self._lock:
            self._streams.pop(stream_id, None)


class _StreamEntry:
    """Private container for per-stream state in :class:`InMemoryStreamStore`.

    Not part of the public API — callers touch the store methods, not
    this struct directly.
    """

    __slots__ = ("complete", "condition", "events")

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.complete: bool = False
        self.condition: asyncio.Condition = asyncio.Condition()


async def tail_from(
    store: StreamStore,
    stream_id: str,
    *,
    since_seq: int = -1,
    wait_timeout: float = 1.0,
) -> AsyncIterator[dict[str, Any]]:
    """Yield stored events for ``stream_id`` then tail live ones.

    The typical use is the resume route's body generator:

    .. code-block:: python

        async def resume_body() -> AsyncIterator[bytes]:
            async for event in tail_from(store, stream_id, since_seq=since):
                yield render_frame(event)

    The iterator terminates when the stream has been marked complete
    **and** the caller has drained every event up to that point —
    guaranteeing the client sees the terminal :class:`FinalEvent` or
    :class:`ErrorEvent` before the connection closes.
    """
    cursor = since_seq
    while True:
        events = await store.get_after(stream_id, cursor)
        for event in events:
            yield event
            seq = int(event.get("seq", cursor))
            if seq > cursor:
                cursor = seq
        if await store.is_complete(stream_id):
            # Flush any events that arrived between the last
            # get_after and the is_complete check so the client
            # never misses the terminal event.
            tail = await store.get_after(stream_id, cursor)
            for event in tail:
                yield event
                seq = int(event.get("seq", cursor))
                if seq > cursor:
                    cursor = seq
            return
        await store.wait(stream_id, timeout=wait_timeout)


def event_to_dict(event: AgentEvent) -> dict[str, Any]:
    """Convert an :class:`AgentEvent` to the plain dict the store persists.

    Lives here so callers (the stream's emit hook) don't have to
    pull in Pydantic just to shape the payload.
    """
    return event.model_dump(mode="json")


__all__ = [
    "InMemoryStreamStore",
    "StreamStore",
    "event_to_dict",
    "tail_from",
]
