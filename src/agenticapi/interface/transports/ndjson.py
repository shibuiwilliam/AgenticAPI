"""Newline-delimited JSON transport for streaming agent endpoints (Phase F3).

Why NDJSON in addition to SSE.

    SSE is the right default for browsers because ``EventSource`` is
    a one-line client, but it's awkward for CLI tools: curl needs
    ``-N``, each frame is three lines (``event: kind`` / ``data:
    {...}`` / blank line), and splitting requires a small parser.

    NDJSON — one JSON object per line — is what the *rest* of the
    toolchain expects: ``jq``, ``curl | jq`` pipelines, Go
    ``bufio.Scanner`` clients, Python ``for line in response:``
    consumers, Kafka / Fluentd log shippers. It's the lowest-friction
    format for anything that isn't a browser.

    Same event types, same :class:`AgentStream`, same lifecycle, same
    audit integration. Only the wire rendering differs: one line of
    JSON per event, terminated with ``\\n``.

Heartbeats.

    Keep-alive over long-running HTTP streams still matters for
    NDJSON (reverse proxies don't care what the body is; they care
    about byte-level silence). The transport emits an empty line
    (``\\n``) every ``heartbeat_interval`` seconds so the connection
    stays warm without injecting a fake JSON object clients would
    have to filter out.

Content-Type.

    We use ``application/x-ndjson``. That's the de-facto registration
    used by Kafka/Fluentd/Elasticsearch even though it's not IANA-
    blessed; the closest IANA-registered type is
    ``application/json-seq`` (RFC 7464), which uses RS prefixes that
    most tooling doesn't understand. ``application/x-ndjson`` is
    what ``jq``/``jnv``/``jless`` treat as streaming JSON by default.
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


_NDJSON_CONTENT_TYPE = "application/x-ndjson"
_HEARTBEAT_LINE = b"\n"
_DEFAULT_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Same nginx-buffering opt-out as the SSE transport — without
    # this header nginx buffers the whole body and the client sees
    # one giant blob at the end.
    "X-Accel-Buffering": "no",
}


def event_to_ndjson_frame(event: AgentEvent) -> bytes:
    """Render one :class:`AgentEvent` as a single NDJSON line.

    The returned bytes end with a single ``\\n`` so the next frame
    starts on its own line. No comment/keep-alive prefix — clients
    split strictly on newlines.
    """
    payload = event.model_dump(mode="json")
    body = json.dumps(payload, ensure_ascii=False)
    return (body + "\n").encode("utf-8")


async def run_ndjson_response(
    *,
    stream: AgentStream,
    handler_task_factory: Callable[[], Awaitable[Any]],
    heartbeat_interval: float = 15.0,
    on_complete: Callable[[AgentStream], Awaitable[None]] | None = None,
) -> StreamingResponse:
    """Wrap an agent handler in an NDJSON-streaming Starlette response.

    Symmetrical with :func:`agenticapi.interface.transports.sse.run_sse_response`.
    The handler is launched as a parallel task so events stream to
    the client as they're emitted.

    Args:
        stream: The :class:`AgentStream` the handler is emitting on.
        handler_task_factory: No-arg coroutine factory that runs the
            handler.
        heartbeat_interval: Seconds between bare-newline keep-alives.
        on_complete: Optional async callback invoked after the
            terminal event is emitted — used by F8 to record the
            full event log into the audit store.

    Returns:
        A Starlette ``StreamingResponse`` with
        ``application/x-ndjson`` content type.
    """
    handler_task = asyncio.create_task(_run_handler(handler_task_factory, stream, on_complete=on_complete))
    body = _ndjson_event_iterator(stream, handler_task, heartbeat_interval)
    return StreamingResponse(
        body,
        media_type=_NDJSON_CONTENT_TYPE,
        headers=dict(_DEFAULT_HEADERS),
    )


async def _run_handler(
    factory: Callable[[], Awaitable[Any]],
    stream: AgentStream,
    *,
    on_complete: Callable[[AgentStream], Awaitable[None]] | None = None,
) -> Any:
    """Invoke the handler and ensure the stream closes cleanly.

    Exceptions become terminal :class:`~agenticapi.interface.stream.ErrorEvent`s,
    returns become terminal :class:`FinalEvent`s. The ``on_complete``
    hook fires *after* the terminal event so the audit integration
    sees a complete event log.
    """
    try:
        result = await factory()
    except Exception as exc:
        logger.error(
            "ndjson_handler_failed",
            stream_id=stream.stream_id,
            error_kind=type(exc).__name__,
            error=str(exc)[:500],
        )
        await stream.emit_error(error_kind=type(exc).__name__, message=str(exc)[:500])
        if on_complete is not None:
            try:
                await on_complete(stream)
            except Exception:
                logger.exception("ndjson_on_complete_failed", stream_id=stream.stream_id)
        return None

    if not any(isinstance(e, FinalEvent) for e in stream.emitted_events):
        await stream.emit_final(result)
    if on_complete is not None:
        try:
            await on_complete(stream)
        except Exception:
            logger.exception("ndjson_on_complete_failed", stream_id=stream.stream_id)
    return result


async def _ndjson_event_iterator(
    stream: AgentStream,
    handler_task: asyncio.Task[Any],
    heartbeat_interval: float,
) -> AsyncIterator[bytes]:
    """Drive the NDJSON wire-format generator.

    Yields one JSON line per emitted event, plus a bare newline every
    ``heartbeat_interval`` seconds of silence. Cleans up the handler
    task on client disconnect.
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
                yield _HEARTBEAT_LINE
                last_emit = asyncio.get_running_loop().time()
                if handler_task.done() and stream.is_closed:
                    return
                continue
            except StopAsyncIteration:
                return

            yield event_to_ndjson_frame(event)
            last_emit = asyncio.get_running_loop().time()
    except (asyncio.CancelledError, ConnectionError, GeneratorExit):
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


__all__ = ["event_to_ndjson_frame", "run_ndjson_response"]
