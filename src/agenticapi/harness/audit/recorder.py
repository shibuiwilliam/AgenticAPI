"""Audit recorder for storing execution traces.

Provides:

* :class:`AuditRecorderProtocol` — the structural interface every
  audit recorder satisfies. Use this in type annotations when you
  want callers to be able to pass in *any* recorder implementation
  (in-memory, SQLite, Postgres, Elasticsearch, …).
* :class:`AuditRecorder` — the default in-memory implementation.
  Capped at ``max_traces``; oldest evicted on overflow.
* :class:`SqliteAuditRecorder` (in :mod:`agenticapi.harness.audit.sqlite_store`)
  — the persistent SQLite-backed implementation, also satisfying the
  protocol.

Phase A3 (persistent audit stores):
    The protocol was promoted from a documentation aspiration to a
    real ``runtime_checkable`` Protocol so multiple implementations
    can ship without forcing inheritance. ``AuditRecorder`` (in-memory)
    keeps its name unchanged for backward compatibility — every
    existing import path still works. New persistent backends live
    next door under :mod:`agenticapi.harness.audit.sqlite_store` and
    are surfaced from :mod:`agenticapi.harness.audit`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

    from agenticapi.harness.audit.trace import ExecutionTrace

logger = structlog.get_logger(__name__)


@runtime_checkable
class AuditRecorderProtocol(Protocol):
    """Structural interface satisfied by every audit recorder.

    The protocol intentionally captures only the **core** methods every
    recorder must provide. Optional extensions (``get_by_id``,
    ``iter_since``, ``vacuum_older_than``) are provided by both shipped
    implementations but are not part of the protocol — callers that
    need them should depend on the concrete class instead.
    """

    async def record(self, trace: ExecutionTrace) -> None:
        """Persist an execution trace."""

    def get_records(
        self,
        *,
        endpoint_name: str | None = None,
        limit: int = 100,
    ) -> list[ExecutionTrace]:
        """Return the most recent traces, optionally filtered by endpoint."""


class AuditRecorder:
    """In-memory audit recorder for execution traces.

    Stores traces in a list and provides retrieval with optional
    filtering by endpoint name and result limiting. Capped at
    ``max_traces`` — oldest traces are evicted on overflow.

    For multi-host or restart-tolerant deployments, use
    :class:`agenticapi.harness.audit.sqlite_store.SqliteAuditRecorder`
    (or another persistent backend) which satisfies the same
    :class:`AuditRecorderProtocol`.

    Example:
        recorder = AuditRecorder()
        await recorder.record(trace)
        records = recorder.get_records(endpoint_name="orders", limit=10)
    """

    def __init__(self, *, max_traces: int = 10000) -> None:
        """Initialize the recorder with an empty trace store.

        Args:
            max_traces: Maximum number of traces to store. Oldest traces
                are evicted when the limit is reached.
        """
        self._traces: list[ExecutionTrace] = []
        self._max_traces = max_traces

    async def record(self, trace: ExecutionTrace) -> None:
        """Record an execution trace.

        Args:
            trace: The execution trace to store.
        """
        self._traces.append(trace)
        # Evict oldest traces if over limit
        if len(self._traces) > self._max_traces:
            evict_count = len(self._traces) - self._max_traces
            self._traces = self._traces[evict_count:]
        logger.info(
            "audit_trace_recorded",
            trace_id=trace.trace_id,
            endpoint_name=trace.endpoint_name,
            intent_action=trace.intent_action,
            duration_ms=trace.execution_duration_ms,
            has_error=trace.error is not None,
        )

    def get_records(
        self,
        *,
        endpoint_name: str | None = None,
        limit: int = 100,
    ) -> list[ExecutionTrace]:
        """Retrieve stored execution traces.

        Args:
            endpoint_name: Filter by endpoint name (None = all endpoints).
            limit: Maximum number of traces to return (most recent first).

        Returns:
            List of execution traces matching the filter criteria.
        """
        traces = self._traces
        if endpoint_name is not None:
            traces = [t for t in traces if t.endpoint_name == endpoint_name]

        # Return most recent first, limited
        return list(reversed(traces[-limit:]))

    def get_by_id(self, trace_id: str) -> ExecutionTrace | None:
        """Look up a single trace by its identifier.

        Returns:
            The matching trace or ``None`` if not found.
        """
        for trace in self._traces:
            if trace.trace_id == trace_id:
                return trace
        return None

    async def iter_since(self, since: datetime) -> AsyncIterator[ExecutionTrace]:
        """Yield every trace recorded at or after ``since``.

        Used by the eval harness to replay production traces (Phase C7).
        Async-shaped for parity with persistent backends that may stream
        rows from the database.
        """
        for trace in self._traces:
            if trace.timestamp >= since:
                yield trace

    async def vacuum_older_than(self, cutoff: datetime) -> int:
        """Drop every trace recorded before ``cutoff``.

        Returns:
            The number of traces removed.
        """
        before = len(self._traces)
        self._traces = [t for t in self._traces if t.timestamp >= cutoff]
        removed = before - len(self._traces)
        if removed:
            logger.info("audit_traces_vacuumed", removed=removed, cutoff=cutoff.isoformat())
        return removed

    def clear(self) -> None:
        """Remove all stored traces."""
        count = len(self._traces)
        self._traces.clear()
        logger.info("audit_traces_cleared", count=count)


# Friendly alias documenting intent at the call site. Both names refer
# to the exact same class — pick whichever reads best in your code.
InMemoryAuditRecorder = AuditRecorder
