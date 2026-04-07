"""Audit recorder for storing execution traces.

Provides in-memory storage of execution traces with filtering
and retrieval. Production deployments should extend this with
persistent storage backends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from agenticapi.harness.audit.trace import ExecutionTrace

logger = structlog.get_logger(__name__)


class AuditRecorder:
    """In-memory audit recorder for execution traces.

    Stores traces in a list and provides retrieval with optional
    filtering by endpoint name and result limiting.

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

    def clear(self) -> None:
        """Remove all stored traces."""
        count = len(self._traces)
        self._traces.clear()
        logger.info("audit_traces_cleared", count=count)
