"""Persistent SQLite-backed :class:`MemoryStore` (Phase C1).

Why stdlib sqlite3, not aiosqlite or SQLAlchemy.
    Same reasoning as :class:`SqliteAuditRecorder`: SQLite is in the
    standard library, wrapping blocking calls in
    :func:`asyncio.to_thread` gives first-class async semantics with
    zero new dependencies, and users who need multi-host or
    multi-writer semantics can swap in a Redis / Postgres backend
    later because the :class:`MemoryStore` protocol is the only
    contract callers depend on.

Schema.
    One table, ``agent_memory``. ``(scope, key)`` is the primary
    key so every write is an ``INSERT OR REPLACE`` — repeated
    writes overwrite in place. Three indices cover the only query
    shapes the store exposes: scope-only listing, scope + kind,
    scope + key_prefix. All query paths are scoped, which is how
    the C3 ``MemoryPolicy.forget`` implementation stays O(index
    lookup) instead of full-table scan.

Serialisation.
    Values are stored as ``json.dumps`` text so anything JSON-round-
    trippable works: primitives, lists, nested dicts, pydantic
    model dumps. Callers that want to store arbitrary Python
    objects should use the normal "dump to dict, put dict" pattern
    — see the examples directory for an illustrated workflow.
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

from agenticapi.runtime.memory.base import MemoryKind, MemoryRecord

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

logger = structlog.get_logger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_memory (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    kind TEXT NOT NULL,
    tags TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
CREATE INDEX IF NOT EXISTS ix_memory_scope ON agent_memory(scope);
CREATE INDEX IF NOT EXISTS ix_memory_scope_kind ON agent_memory(scope, kind);
CREATE INDEX IF NOT EXISTS ix_memory_updated_at ON agent_memory(updated_at DESC);
"""


class SqliteMemoryStore:
    """Persistent memory store backed by a single SQLite file.

    Satisfies :class:`MemoryStore` structurally (no inheritance
    required). Drop-in for any
    :class:`~agenticapi.runtime.memory.base.InMemoryMemoryStore`
    usage:

    .. code-block:: python

        from agenticapi.runtime.memory import MemoryRecord, SqliteMemoryStore

        memory = SqliteMemoryStore(path="./memory.sqlite")
        await memory.put(MemoryRecord(
            scope="user:alice",
            key="currency",
            value="EUR",
        ))
        record = await memory.get(scope="user:alice", key="currency")

    Concurrency.
        One long-lived connection with ``check_same_thread=False``
        and ``isolation_level=None`` (autocommit). Writes are
        serialised through an :class:`asyncio.Lock` so concurrent
        ``put`` calls don't interleave. Reads hit the same
        connection without locking — SQLite is fine with many
        concurrent readers and one writer.
    """

    def __init__(self, *, path: str | Path) -> None:
        """Open (or create) the backing SQLite file.

        Args:
            path: Filesystem path to the SQLite file. Pass
                ``":memory:"`` for a throwaway in-process store
                that disappears when the process exits — handy for
                unit tests and notebooks.
        """
        self._path = str(path)
        self._write_lock = asyncio.Lock()
        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        yield self._conn

    def close(self) -> None:
        """Close the underlying connection. Idempotent."""
        with contextlib.suppress(sqlite3.ProgrammingError):
            self._conn.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    # ------------------------------------------------------------------
    # MemoryStore protocol
    # ------------------------------------------------------------------

    async def put(self, record: MemoryRecord) -> None:
        """Persist a record, overwriting any existing ``(scope, key)`` row."""
        row = _record_to_row(record)
        async with self._write_lock:
            await asyncio.to_thread(self._insert_row, row)
        logger.debug(
            "memory_put",
            scope=record.scope,
            key=record.key,
            kind=record.kind.value,
            has_tags=bool(record.tags),
        )

    async def get(self, *, scope: str, key: str) -> MemoryRecord | None:
        """Look up a single record by ``(scope, key)``."""

        def _do() -> sqlite3.Row | None:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT * FROM agent_memory WHERE scope = ? AND key = ?",
                    (scope, key),
                )
                result: sqlite3.Row | None = cur.fetchone()
                return result

        row = await asyncio.to_thread(_do)
        if row is None:
            return None
        return _row_to_record(row)

    async def search(
        self,
        *,
        scope: str,
        kind: MemoryKind | None = None,
        key_prefix: str | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        """Return scoped records matching the optional filters.

        Ordered by ``updated_at`` DESC so the most-recently-written
        records come first. Clients can iterate the returned list
        to implement their own recency windows.
        """

        def _do() -> list[sqlite3.Row]:
            clauses = ["scope = ?"]
            params: list[Any] = [scope]
            if kind is not None:
                clauses.append("kind = ?")
                params.append(kind.value)
            if key_prefix is not None:
                clauses.append("key LIKE ?")
                params.append(f"{key_prefix}%")
            sql = "SELECT * FROM agent_memory WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC LIMIT ?"
            params.append(int(limit))
            with self._connect() as conn:
                cur = conn.execute(sql, params)
                return list(cur.fetchall())

        rows = await asyncio.to_thread(_do)
        records = [_row_to_record(row) for row in rows]
        if tag is not None:
            records = [r for r in records if tag in r.tags]
        return records[:limit]

    async def forget(self, *, scope: str, key: str | None = None) -> int:
        """Hard-delete records.

        When ``key`` is ``None`` the entire scope is removed — the
        GDPR Article 17 primitive C3 hangs off of. Returns the
        number of rows actually removed so callers can assert on
        the count in tests.
        """

        def _do() -> int:
            with self._connect() as conn:
                if key is None:
                    cur = conn.execute("DELETE FROM agent_memory WHERE scope = ?", (scope,))
                else:
                    cur = conn.execute(
                        "DELETE FROM agent_memory WHERE scope = ? AND key = ?",
                        (scope, key),
                    )
                return int(cur.rowcount)

        async with self._write_lock:
            removed = await asyncio.to_thread(_do)
        if removed:
            logger.info(
                "memory_forget",
                scope=scope,
                key=key,
                removed=removed,
            )
        return removed

    # ------------------------------------------------------------------
    # Extras (not part of the protocol)
    # ------------------------------------------------------------------

    async def count(self) -> int:
        """Total number of rows. Test helper."""

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute("SELECT COUNT(*) FROM agent_memory")
                return int(cur.fetchone()[0])

        return await asyncio.to_thread(_do)

    async def clear(self) -> None:
        """Drop every row. Test-only convenience."""

        def _do() -> None:
            with self._connect() as conn:
                conn.execute("DELETE FROM agent_memory")

        async with self._write_lock:
            await asyncio.to_thread(_do)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _insert_row(self, row: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            # We let SQLite bump ``updated_at`` via the application
            # code above rather than via a trigger so the behaviour
            # is identical to the in-memory store.
            conn.execute(
                "INSERT INTO agent_memory "
                "(scope, key, value, kind, tags, timestamp, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(scope, key) DO UPDATE SET "
                "value = excluded.value, "
                "kind = excluded.kind, "
                "tags = excluded.tags, "
                "updated_at = excluded.updated_at",
                row,
            )


# ---------------------------------------------------------------------------
# Row ↔ record conversion
# ---------------------------------------------------------------------------


def _record_to_row(record: MemoryRecord) -> tuple[Any, ...]:
    """Convert a :class:`MemoryRecord` into a sqlite row tuple."""
    return (
        record.scope,
        record.key,
        json.dumps(record.value, default=str),
        record.kind.value,
        json.dumps(record.tags),
        record.timestamp.astimezone(UTC).isoformat(),
        record.updated_at.astimezone(UTC).isoformat(),
    )


def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
    """Convert a sqlite row back into a :class:`MemoryRecord`."""
    try:
        value = json.loads(row["value"])
    except (TypeError, ValueError):
        value = row["value"]
    try:
        tags = json.loads(row["tags"])
    except (TypeError, ValueError):
        tags = []
    timestamp = datetime.fromisoformat(row["timestamp"])
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    updated_at = datetime.fromisoformat(row["updated_at"])
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return MemoryRecord(
        scope=row["scope"],
        key=row["key"],
        value=value,
        kind=MemoryKind(row["kind"]),
        tags=list(tags) if isinstance(tags, list) else [],
        timestamp=timestamp,
        updated_at=updated_at,
    )


__all__ = ["SqliteMemoryStore"]
