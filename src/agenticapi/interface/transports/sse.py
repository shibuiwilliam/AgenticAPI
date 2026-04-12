"""Server-Sent Events transport for streaming agent endpoints (Phase F2).

Why SSE.

    SSE is the simplest possible streaming HTTP transport: text body,
    one event per ``event: kind\\ndata: json\\n\\n`` block, browser-
    native support via ``EventSource``, works through every reverse
    proxy and CDN with no special configuration. We pick it as the
    *default* streaming transport because it's the lowest-friction
    way to ship streaming to a real user.

    NDJSON (F3) and WebSocket (F4) ship as alternative transports
    later. The default endpoint declaration ``streaming="sse"`` uses
    this module.

What this module does.

    :func:`run_sse_response` consumes an :class:`AgentStream` and
    returns a Starlette ``StreamingResponse`` that emits SSE frames
    until the stream closes. The handler is launched as an
    ``asyncio.Task`` and runs in parallel with the SSE transport
    loop, so the client sees events as they're emitted (not buffered
    until the handler returns).

Heartbeats.

    SSE connections are killed by reverse proxies and CDNs after
    ~30s of silence. The transport emits ``: keepalive`` comment
    lines every ``heartbeat_interval`` seconds (default 15s) so
    long-running handlers don't get cut off.

Cancellation.

    When the client disconnects, Starlette's ``StreamingResponse``
    raises an exception inside the generator. We catch it, mark the
    stream closed, and cancel the handler task so background work
    doesn't continue uselessly. The handler task is awaited (with a
    short grace period) so any open async resources get a chance to
    clean up.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

import structlog
from starlette.responses import StreamingResponse

from agenticapi.interface.stream import AgentEvent, AgentStream, FinalEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger = structlog.get_logger(__name__)


_SSE_CONTENT_TYPE = "text/event-stream"
_HEARTBEAT_LINE = b": keepalive\n\n"
_DEFAULT_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Disable buffering for nginx and friends — without this header,
    # an upstream nginx may buffer the entire response and defeat the
    # whole point of streaming.
    "X-Accel-Buffering": "no",
}


def event_to_sse_frame(event: AgentEvent) -> bytes:
    """Render one :class:`AgentEvent` as an SSE frame.

    Format::

        event: <kind>
        data: <json blob>
        \n

    The blank line at the end is what makes the browser's
    ``EventSource`` deliver the event. The ``id:`` field is omitted
    on purpose — clients use ``seq`` from the event payload itself
    so the SSE-level ``Last-Event-ID`` reconnect mechanism is not
    needed (F7 will handle resumability via the dedicated resume
    endpoint instead).
    """
    payload = event.model_dump(mode="json")
    body = json.dumps(payload, ensure_ascii=False)
    frame = f"event: {event.kind}\ndata: {body}\n\n"
    return frame.encode("utf-8")


async def run_sse_response(
    *,
    stream: AgentStream,
    handler_task_factory: Callable[[], Awaitable[Any]],
    heartbeat_interval: float = 15.0,
    on_complete: Callable[[AgentStream], Awaitable[None]] | None = None,
) -> StreamingResponse:
    """Wrap an agent handler in an SSE-streaming Starlette response.

    Args:
        stream: The :class:`AgentStream` the handler is emitting on.
            The framework already injected this into the handler via
            the dependency solver; we read events from its consume
            queue.
        handler_task_factory: A no-arg coroutine factory that, when
            awaited, runs the handler. We launch it as a parallel
            task so the SSE transport can begin streaming events
            before the handler returns.
        heartbeat_interval: Seconds between ``: keepalive`` comment
            lines. Defaults to 15s — well under the 30s timeout most
            proxies impose.
        on_complete: Optional async callback invoked **after** the
            handler returns and the terminal FinalEvent / ErrorEvent
            has been emitted but **before** the SSE transport closes
            the stream. Used by Phase F8 to record the full event log
            into the audit trace, including the terminal event.

    Returns:
        A Starlette ``StreamingResponse`` ready to be returned from
        the endpoint handler.
    """
    handler_task = asyncio.create_task(_run_handler(handler_task_factory, stream, on_complete=on_complete))
    body = _sse_event_iterator(stream, handler_task, heartbeat_interval)
    return StreamingResponse(
        body,
        media_type=_SSE_CONTENT_TYPE,
        headers=dict(_DEFAULT_HEADERS),
    )


async def _run_handler(
    factory: Callable[[], Awaitable[Any]],
    stream: AgentStream,
    *,
    on_complete: Callable[[AgentStream], Awaitable[None]] | None = None,
) -> Any:
    """Invoke the handler and ensure the stream closes on its way out.

    The handler may emit events directly via ``stream.emit_*`` and
    may also return a value. The return value is converted into a
    terminal :class:`FinalEvent` so the client always sees a clean
    end-of-stream marker. Exceptions become terminal
    :class:`agenticapi.interface.stream.ErrorEvent`s.

    After the terminal event is emitted, the optional
    :func:`on_complete` callback is invoked with the now-complete
    stream so callers (Phase F8) can record the full event log to
    the audit store.
    """
    try:
        result = await factory()
    except Exception as exc:
        logger.error(
            "sse_handler_failed",
            stream_id=stream.stream_id,
            error_kind=type(exc).__name__,
            error=str(exc)[:500],
        )
        await stream.emit_error(error_kind=type(exc).__name__, message=str(exc)[:500])
        if on_complete is not None:
            try:
                await on_complete(stream)
            except Exception:
                logger.exception("sse_on_complete_failed", stream_id=stream.stream_id)
        return None

    # Don't emit a duplicate FinalEvent if the handler already
    # produced one explicitly.
    if not any(isinstance(e, FinalEvent) for e in stream.emitted_events):
        await stream.emit_final(result)
    if on_complete is not None:
        try:
            await on_complete(stream)
        except Exception:
            logger.exception("sse_on_complete_failed", stream_id=stream.stream_id)
    return result


async def _sse_event_iterator(
    stream: AgentStream,
    handler_task: asyncio.Task[Any],
    heartbeat_interval: float,
) -> AsyncIterator[bytes]:
    """Drive the SSE wire-format generator.

    Yields one SSE frame per emitted event, plus a heartbeat
    ``: keepalive`` line whenever ``heartbeat_interval`` elapses with
    no events. Cleans up the handler task on client disconnect.
    """
    consumer = stream.consume()
    last_emit = asyncio.get_running_loop().time()

    try:
        while True:
            now = asyncio.get_running_loop().time()
            since_last = now - last_emit
            wait_budget = max(0.05, heartbeat_interval - since_last)
            try:
                event = await asyncio.wait_for(consumer.__anext__(), timeout=wait_budget)
            except TimeoutError:
                # No event in this window — emit a heartbeat to keep
                # the connection alive across reverse proxies.
                yield _HEARTBEAT_LINE
                last_emit = asyncio.get_running_loop().time()
                if handler_task.done() and stream.is_closed:
                    return
                continue
            except StopAsyncIteration:
                return

            yield event_to_sse_frame(event)
            last_emit = asyncio.get_running_loop().time()
    except (asyncio.CancelledError, ConnectionError, GeneratorExit):
        # Client disconnected. Mark the stream closed and cancel the
        # handler task so background work doesn't outlive the request.
        await stream.close()
        if not handler_task.done():
            handler_task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(handler_task, timeout=2.0)
        raise
    finally:
        if not handler_task.done():
            with contextlib.suppress(Exception):
                await handler_task


__all__ = ["event_to_sse_frame", "run_sse_response"]
