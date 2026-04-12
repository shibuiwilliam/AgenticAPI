"""SQLite-backed persistent ``AuditRecorder`` implementation.

The Phase 1 in-memory :class:`agenticapi.harness.audit.recorder.AuditRecorder`
is fine for unit tests and dev loops, but production agent APIs need
the audit trail to **survive process restarts and be queryable** —
otherwise compliance, replay-from-audit (Phase C7), and incident
forensics are impossible.

Why the standard library, not aiosqlite or SQLAlchemy.
    SQLite is in the Python standard library. Wrapping its blocking
    calls in :func:`asyncio.to_thread` gives us first-class async
    semantics with **zero new dependencies** and zero risk of version
    drift. Users with high-throughput needs can swap in a Postgres or
    Elasticsearch implementation later — the protocol stays the same.

Schema.
    One table, ``audit_traces``. Trace ID is the primary key. Two
    indices (timestamp DESC, endpoint_name) cover the only query
    patterns the recorder needs: "most recent N", "filter by endpoint",
    and "since timestamp". Larger schemas can be migrated cleanly
    because the trace itself is stored as JSON in the
    ``execution_result``/``policy_evaluations``/``llm_usage`` columns —
    new fields don't require ALTER TABLE.

This module is part of A3 in :doc:`/CLAUDE_ENHANCE`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.harness.audit.trace import ExecutionTrace

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

logger = structlog.get_logger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_traces (
    trace_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    endpoint_name TEXT NOT NULL,
    intent_raw TEXT NOT NULL,
    intent_action TEXT NOT NULL,
    generated_code TEXT NOT NULL,
    reasoning TEXT,
    execution_duration_ms REAL NOT NULL,
    execution_result TEXT,
    error TEXT,
    llm_usage TEXT,
    policy_evaluations TEXT,
    approval_request_id TEXT,
    stream_events TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_timestamp ON audit_traces(timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_audit_endpoint ON audit_traces(endpoint_name);
"""

# Idempotent migration to add stream_events to existing databases
# created before Phase F8 landed. SQLite ignores ALTER TABLE ADD
# COLUMN if the column already exists in newer versions, but to stay
# portable across versions we wrap it in a try/except inside __init__.
_MIGRATIONS_SQL: list[str] = [
    "ALTER TABLE audit_traces ADD COLUMN stream_events TEXT",
]


class SqliteAuditRecorder:
    """Persistent :class:`AuditRecorder` backed by a single SQLite database file.

    Satisfies the :class:`AuditRecorderProtocol` (structurally — no
    inheritance). Drop-in for the in-memory recorder:

    .. code-block:: python

        from agenticapi.harness import HarnessEngine
        from agenticapi.harness.audit import SqliteAuditRecorder

        recorder = SqliteAuditRecorder(path="./audit.sqlite")
        harness = HarnessEngine(audit_recorder=recorder, policies=[...])

    All methods are async even though SQLite is blocking — the
    blocking calls are off-loaded to a worker thread via
    :func:`asyncio.to_thread` so the event loop is never starved.

    Concurrency.
        SQLite supports many concurrent readers and one concurrent
        writer. We open the database with ``check_same_thread=False``
        and ``isolation_level=None`` (autocommit), and serialise writes
        through an :class:`asyncio.Lock`. This is correct for the
        agent-audit workload: writes happen at request rate, queries
        are dashboards, and we never need long transactions.
    """

    def __init__(
        self,
        *,
        path: str | Path,
        max_traces: int | None = None,
    ) -> None:
        """Initialize the recorder.

        Args:
            path: Filesystem path to the SQLite database file. Created
                if missing. Use ``":memory:"`` for an in-process database
                that disappears on process exit (handy for tests).
            max_traces: Optional hard cap on the number of stored
                traces. When set, every ``record()`` call also evicts
                the oldest rows so the table size stays bounded.
                ``None`` (default) keeps everything until the user
                runs ``vacuum_older_than()``.
        """
        self._path = str(path)
        self._max_traces = max_traces
        self._write_lock = asyncio.Lock()
        # Hold a single long-lived connection so:
        #   1. ``:memory:`` databases survive across calls (each new
        #      connection to ``:memory:`` would otherwise be a fresh
        #      empty DB).
        #   2. File-based stores avoid the open/close churn at request
        #      rate. SQLite is happy with one writer + many readers
        #      from a single connection (we serialise writes via
        #      ``_write_lock``).
        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        self._conn.row_factory = sqlite3.Row
        # Schema creation is idempotent.
        self._conn.executescript(_SCHEMA_SQL)
        # Apply idempotent migrations for databases created before
        # newer columns landed. ``ALTER TABLE ADD COLUMN`` raises
        # ``sqlite3.OperationalError`` when the column already exists,
        # which we silently swallow — the migration is a no-op in
        # that case.
        for migration in _MIGRATIONS_SQL:
            with contextlib.suppress(sqlite3.OperationalError):
                self._conn.execute(migration)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield the long-lived connection (no open/close)."""
        yield self._conn

    def close(self) -> None:
        """Close the underlying SQLite connection. Idempotent."""
        with contextlib.suppress(sqlite3.ProgrammingError):
            self._conn.close()

    def __del__(self) -> None:
        # Best-effort cleanup. Users should call ``close()`` explicitly
        # in production code paths.
        with contextlib.suppress(Exception):
            self.close()

    # ------------------------------------------------------------------
    # AuditRecorderProtocol — record + get_records
    # ------------------------------------------------------------------

    async def record(self, trace: ExecutionTrace) -> None:
        """Persist an execution trace to SQLite."""
        row = _trace_to_row(trace)
        async with self._write_lock:
            await asyncio.to_thread(self._insert_row, row)
            if self._max_traces is not None:
                await asyncio.to_thread(self._vacuum_to_max, self._max_traces)
        logger.info(
            "audit_trace_recorded",
            backend="sqlite",
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
        """Return the ``limit`` most recent traces, optionally filtered.

        This call is **synchronous** to keep the protocol identical to
        the in-memory recorder. Internally it opens a short-lived
        connection — the typical query pattern (a dashboard ticking
        every few seconds) does not warrant async overhead. Callers
        on a hot path should use :meth:`iter_since` instead, which is
        async-stream-shaped.
        """
        return self._select_recent(endpoint_name=endpoint_name, limit=limit)

    # ------------------------------------------------------------------
    # Optional extensions: get_by_id, iter_since, vacuum
    # ------------------------------------------------------------------

    def get_by_id(self, trace_id: str) -> ExecutionTrace | None:
        """Look up a single trace by its identifier."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM audit_traces WHERE trace_id = ?",
                (trace_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_trace(row)

    async def iter_since(self, since: datetime) -> AsyncIterator[ExecutionTrace]:
        """Yield every trace recorded at or after ``since``.

        Streams rows so very large audit stores don't materialise the
        whole result set in memory.
        """
        cutoff = since.astimezone(UTC).isoformat()

        def _fetch_chunk(after_id: str | None, batch_size: int = 200) -> list[sqlite3.Row]:
            with self._connect() as conn:
                if after_id is None:
                    cur = conn.execute(
                        "SELECT * FROM audit_traces WHERE timestamp >= ? ORDER BY timestamp ASC, trace_id ASC LIMIT ?",
                        (cutoff, batch_size),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM audit_traces WHERE timestamp >= ? "
                        "AND trace_id > ? "
                        "ORDER BY timestamp ASC, trace_id ASC LIMIT ?",
                        (cutoff, after_id, batch_size),
                    )
                return list(cur.fetchall())

        last_id: str | None = None
        while True:
            chunk = await asyncio.to_thread(_fetch_chunk, last_id)
            if not chunk:
                return
            for row in chunk:
                last_id = row["trace_id"]
                yield _row_to_trace(row)

    async def vacuum_older_than(self, cutoff: datetime) -> int:
        """Drop every trace recorded before ``cutoff``.

        Returns:
            The number of rows removed.
        """
        cutoff_iso = cutoff.astimezone(UTC).isoformat()

        def _delete() -> int:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM audit_traces WHERE timestamp < ?",
                    (cutoff_iso,),
                )
                return cur.rowcount

        async with self._write_lock:
            removed = await asyncio.to_thread(_delete)
        if removed:
            logger.info("audit_traces_vacuumed", backend="sqlite", removed=removed, cutoff=cutoff_iso)
        return int(removed)

    async def count(self) -> int:
        """Return the total number of stored traces."""

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute("SELECT COUNT(*) FROM audit_traces")
                return int(cur.fetchone()[0])

        return await asyncio.to_thread(_do)

    async def clear(self) -> None:
        """Remove every trace. Test-only / dev-only operation."""

        def _do() -> None:
            with self._connect() as conn:
                conn.execute("DELETE FROM audit_traces")

        async with self._write_lock:
            await asyncio.to_thread(_do)
        logger.info("audit_traces_cleared", backend="sqlite")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert_row(self, row: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO audit_traces ("
                "trace_id, timestamp, endpoint_name, intent_raw, intent_action, "
                "generated_code, reasoning, execution_duration_ms, execution_result, "
                "error, llm_usage, policy_evaluations, approval_request_id, stream_events"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    def _vacuum_to_max(self, max_traces: int) -> None:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM audit_traces")
            count = int(cur.fetchone()[0])
            if count <= max_traces:
                return
            excess = count - max_traces
            conn.execute(
                "DELETE FROM audit_traces WHERE trace_id IN ("
                "SELECT trace_id FROM audit_traces ORDER BY timestamp ASC LIMIT ?"
                ")",
                (excess,),
            )

    def _select_recent(
        self,
        *,
        endpoint_name: str | None,
        limit: int,
    ) -> list[ExecutionTrace]:
        with self._connect() as conn:
            if endpoint_name is None:
                cur = conn.execute(
                    "SELECT * FROM audit_traces ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM audit_traces WHERE endpoint_name = ? ORDER BY timestamp DESC LIMIT ?",
                    (endpoint_name, limit),
                )
            rows = list(cur.fetchall())
        return [_row_to_trace(row) for row in rows]


# ---------------------------------------------------------------------------
# Row <-> ExecutionTrace conversion
# ---------------------------------------------------------------------------


def _trace_to_row(trace: ExecutionTrace) -> tuple[Any, ...]:
    """Convert an :class:`ExecutionTrace` into a sqlite row tuple."""
    return (
        trace.trace_id,
        trace.timestamp.astimezone(UTC).isoformat(),
        trace.endpoint_name,
        trace.intent_raw,
        trace.intent_action,
        trace.generated_code,
        trace.reasoning,
        trace.execution_duration_ms,
        json.dumps(trace.execution_result, default=str) if trace.execution_result is not None else None,
        trace.error,
        json.dumps(trace.llm_usage) if trace.llm_usage is not None else None,
        json.dumps(trace.policy_evaluations) if trace.policy_evaluations else None,
        trace.approval_request_id,
        json.dumps(trace.stream_events) if trace.stream_events else None,
    )


def _row_to_trace(row: sqlite3.Row) -> ExecutionTrace:
    """Convert a sqlite row back into an :class:`ExecutionTrace`."""
    timestamp = datetime.fromisoformat(row["timestamp"])
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    execution_result: Any = None
    if row["execution_result"] is not None:
        try:
            execution_result = json.loads(row["execution_result"])
        except (TypeError, ValueError):
            execution_result = row["execution_result"]

    llm_usage: dict[str, int] | None = None
    if row["llm_usage"] is not None:
        try:
            parsed_usage = json.loads(row["llm_usage"])
            if isinstance(parsed_usage, dict):
                llm_usage = {str(k): int(v) for k, v in parsed_usage.items()}
        except (TypeError, ValueError):
            llm_usage = None

    policy_evaluations: list[dict[str, Any]] = []
    if row["policy_evaluations"] is not None:
        try:
            parsed_policies = json.loads(row["policy_evaluations"])
            if isinstance(parsed_policies, list):
                policy_evaluations = [dict(item) for item in parsed_policies if isinstance(item, dict)]
        except (TypeError, ValueError):
            policy_evaluations = []

    stream_events: list[dict[str, Any]] = []
    # Defensive: ``row["stream_events"]`` raises IndexError when the
    # column does not exist (e.g. a database created before the F8
    # migration). We treat that case as "no streamed events".
    try:
        raw_stream = row["stream_events"]
    except (IndexError, KeyError):
        raw_stream = None
    if raw_stream is not None:
        try:
            parsed_stream = json.loads(raw_stream)
            if isinstance(parsed_stream, list):
                stream_events = [dict(item) for item in parsed_stream if isinstance(item, dict)]
        except (TypeError, ValueError):
            stream_events = []

    return ExecutionTrace(
        trace_id=row["trace_id"],
        endpoint_name=row["endpoint_name"],
        timestamp=timestamp,
        intent_raw=row["intent_raw"],
        intent_action=row["intent_action"],
        generated_code=row["generated_code"],
        reasoning=row["reasoning"],
        policy_evaluations=policy_evaluations,
        execution_result=execution_result,
        execution_duration_ms=row["execution_duration_ms"],
        error=row["error"],
        llm_usage=llm_usage,
        approval_request_id=row["approval_request_id"],
        stream_events=stream_events,
    )


__all__ = ["SqliteAuditRecorder"]
