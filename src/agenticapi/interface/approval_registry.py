"""In-process approval registry for streaming endpoints (Phase F5).

The :class:`AgentStream.request_approval` API needs a registry where
pending approval requests can be looked up by id when the resume
endpoint receives the user's decision. This module provides that
registry plus the helpers the framework's HTTP layer uses to wire
the resume endpoint up.

Why in-process (and what to swap later).

    Single-process deployments are the common case for early agent
    apps. The registry below uses a plain dict guarded by an
    :class:`asyncio.Lock`. Approvals can survive multi-second waits
    (the human reads the prompt, clicks a button) but they cannot
    survive a process restart or be served from a different host.

    Multi-host deployments would swap this for a Redis-backed
    registry that publishes resume events on a pub/sub channel. The
    interface is a single class so that swap is small. Phase F7
    (resumability) will land that backend.

Lifecycle.

    1. Handler calls ``stream.request_approval(...)``.
    2. The factory provided to the :class:`AgentStream` produces a
       fresh :class:`ApprovalHandle` and registers it under a
       freshly-minted ``approval_id``.
    3. Stream emits :class:`ApprovalRequestedEvent` with that id.
    4. Client (or human via UI) POSTs the chosen option to
       ``/agent/{name}/resume/{stream_id}``.
    5. The framework looks up the active handle by ``stream_id``
       and calls :meth:`ApprovalHandle.resolve`, waking the
       suspended handler.
    6. Stream emits :class:`ApprovalResolvedEvent` and continues.

    A configurable timeout (set per-call) determines what happens if
    the human never answers — the configured ``default_decision`` is
    used and the event is marked ``timed_out=True``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import structlog

from agenticapi.interface.stream import ApprovalHandle

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


class ApprovalRegistry:
    """Maps ``stream_id`` to in-flight :class:`ApprovalHandle` objects.

    A single registry instance lives on the :class:`AgenticApp`. Each
    streaming request gets its own ``stream_id`` and any number of
    approval handles registered against it (handlers can call
    ``request_approval`` more than once per request).
    """

    def __init__(self) -> None:
        # stream_id → list of (approval_id, handle). We keep a list
        # rather than a dict because handlers can request more than
        # one approval per request, and the resume endpoint takes the
        # *oldest unresolved* approval by default — clients without
        # an explicit approval_id get FIFO semantics.
        self._handles: dict[str, list[tuple[str, ApprovalHandle]]] = {}
        self._lock = asyncio.Lock()

    def create_handle_factory(
        self,
        stream_id: str,
        *,
        default_decision: str = "reject",
    ) -> Callable[[str], ApprovalHandle]:
        """Return a factory the :class:`AgentStream` calls per approval.

        The factory has the same signature the stream module declares
        in its ``ApprovalHandleFactoryType`` alias. It mints a fresh
        ``approval_id`` per call and registers the resulting handle
        under ``stream_id`` so the resume endpoint can find it later.
        """

        def _factory(_stream_id: str) -> ApprovalHandle:
            approval_id = uuid.uuid4().hex
            handle = ApprovalHandle(approval_id=approval_id, default_decision=default_decision)
            # Synchronous registration is fine: we hold the GIL and
            # we never await between mint and add.
            self._handles.setdefault(_stream_id, []).append((approval_id, handle))
            logger.debug(
                "approval_handle_registered",
                stream_id=_stream_id,
                approval_id=approval_id,
            )
            return handle

        return _factory

    async def resolve(
        self,
        stream_id: str,
        decision: str,
        *,
        approval_id: str | None = None,
    ) -> bool:
        """Resolve a pending approval for ``stream_id``.

        Args:
            stream_id: The stream the approval was requested on.
            decision: The user's choice.
            approval_id: Optional specific approval id. When ``None``,
                resolves the oldest unresolved handle (FIFO).

        Returns:
            ``True`` if a handle was found and resolved, ``False``
            otherwise.
        """
        async with self._lock:
            entries = self._handles.get(stream_id) or []
            target: ApprovalHandle | None = None
            target_idx: int | None = None
            for idx, (handle_id, handle) in enumerate(entries):
                if approval_id is not None and handle_id != approval_id:
                    continue
                if handle._event.is_set():
                    continue
                target = handle
                target_idx = idx
                break
            if target is None:
                logger.warning(
                    "approval_resolve_no_match",
                    stream_id=stream_id,
                    approval_id=approval_id,
                )
                return False
            target.resolve(decision)
            # Drop the handle so the registry doesn't accumulate
            # forever even when callers don't explicitly clean up.
            assert target_idx is not None
            entries.pop(target_idx)
            if not entries:
                self._handles.pop(stream_id, None)
            logger.info(
                "approval_resolved",
                stream_id=stream_id,
                approval_id=target.approval_id,
                decision=decision,
            )
            return True

    def has_pending(self, stream_id: str) -> bool:
        """True when ``stream_id`` has at least one unresolved handle."""
        entries = self._handles.get(stream_id) or []
        return any(not h._event.is_set() for _, h in entries)

    def discard(self, stream_id: str) -> None:
        """Drop every handle for ``stream_id`` (called on stream close)."""
        self._handles.pop(stream_id, None)


__all__ = ["ApprovalRegistry"]
