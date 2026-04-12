"""Unit tests for ``SqliteAuditRecorder`` (Phase A3).

Covers the protocol compliance, round-trip fidelity, filter/limit
queries, ``get_by_id``, ``iter_since``, ``vacuum_older_than``,
``count``, ``clear``, and ``max_traces`` enforcement.

Tests use ``:memory:`` databases so they leave no on-disk artefacts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agenticapi.harness.audit import (
    AuditRecorder,
    AuditRecorderProtocol,
    ExecutionTrace,
    InMemoryAuditRecorder,
    SqliteAuditRecorder,
)


def _make_trace(
    trace_id: str = "t1",
    *,
    endpoint: str = "orders.query",
    when: datetime | None = None,
    error: str | None = None,
) -> ExecutionTrace:
    return ExecutionTrace(
        trace_id=trace_id,
        endpoint_name=endpoint,
        timestamp=when or datetime.now(tz=UTC),
        intent_raw="show recent orders",
        intent_action="read",
        generated_code="result = db.query('select 1')",
        reasoning="trivial",
        execution_duration_ms=12.345,
        execution_result={"rows": [1, 2, 3], "total": 3},
        error=error,
        llm_usage={"input_tokens": 100, "output_tokens": 25},
        policy_evaluations=[
            {"policy_name": "CodePolicy", "allowed": True, "violations": [], "warnings": []},
            {"policy_name": "DataPolicy", "allowed": True, "violations": [], "warnings": []},
        ],
    )


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_in_memory_satisfies_protocol(self) -> None:
        rec = AuditRecorder()
        assert isinstance(rec, AuditRecorderProtocol)

    def test_sqlite_satisfies_protocol(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        assert isinstance(rec, AuditRecorderProtocol)

    def test_in_memory_alias(self) -> None:
        """``InMemoryAuditRecorder`` is just a friendlier name for ``AuditRecorder``."""
        assert InMemoryAuditRecorder is AuditRecorder


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestSqliteRoundTrip:
    async def test_record_and_get_by_id(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        trace = _make_trace("abc")
        await rec.record(trace)
        fetched = rec.get_by_id("abc")
        assert fetched is not None
        assert fetched.trace_id == "abc"
        assert fetched.endpoint_name == "orders.query"
        assert fetched.intent_action == "read"
        assert fetched.execution_duration_ms == 12.345

    async def test_complex_fields_preserved(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        trace = _make_trace("abc")
        await rec.record(trace)
        fetched = rec.get_by_id("abc")
        assert fetched is not None
        # JSON-serialised columns round-trip correctly.
        assert fetched.execution_result == {"rows": [1, 2, 3], "total": 3}
        assert fetched.llm_usage == {"input_tokens": 100, "output_tokens": 25}
        assert len(fetched.policy_evaluations) == 2
        assert fetched.policy_evaluations[0]["policy_name"] == "CodePolicy"

    async def test_error_field_preserved(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        trace = _make_trace("err1", error="boom")
        await rec.record(trace)
        fetched = rec.get_by_id("err1")
        assert fetched is not None
        assert fetched.error == "boom"

    async def test_get_by_id_missing(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        assert rec.get_by_id("nonexistent") is None

    async def test_record_replaces_on_conflict(self) -> None:
        """Inserting the same trace_id twice updates the row (idempotent)."""
        rec = SqliteAuditRecorder(path=":memory:")
        await rec.record(_make_trace("dup", endpoint="ep1"))
        await rec.record(_make_trace("dup", endpoint="ep2"))
        fetched = rec.get_by_id("dup")
        assert fetched is not None
        assert fetched.endpoint_name == "ep2"


# ---------------------------------------------------------------------------
# get_records
# ---------------------------------------------------------------------------


class TestSqliteGetRecords:
    async def test_returns_most_recent_first(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        now = datetime.now(tz=UTC)
        await rec.record(_make_trace("old", when=now - timedelta(seconds=10)))
        await rec.record(_make_trace("mid", when=now - timedelta(seconds=5)))
        await rec.record(_make_trace("new", when=now))
        rows = rec.get_records(limit=10)
        assert [r.trace_id for r in rows] == ["new", "mid", "old"]

    async def test_filter_by_endpoint(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        await rec.record(_make_trace("o1", endpoint="orders.query"))
        await rec.record(_make_trace("u1", endpoint="users.query"))
        await rec.record(_make_trace("o2", endpoint="orders.query"))
        orders = rec.get_records(endpoint_name="orders.query", limit=10)
        users = rec.get_records(endpoint_name="users.query", limit=10)
        assert {r.trace_id for r in orders} == {"o1", "o2"}
        assert {r.trace_id for r in users} == {"u1"}

    async def test_limit_applies(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        for i in range(20):
            await rec.record(_make_trace(f"t{i:02d}"))
        rows = rec.get_records(limit=5)
        assert len(rows) == 5


# ---------------------------------------------------------------------------
# iter_since
# ---------------------------------------------------------------------------


class TestSqliteIterSince:
    async def test_iter_since_streams_in_order(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        now = datetime.now(tz=UTC)
        for i in range(5):
            await rec.record(_make_trace(f"t{i}", when=now + timedelta(seconds=i)))

        seen: list[str] = []
        async for trace in rec.iter_since(now - timedelta(seconds=1)):
            seen.append(trace.trace_id)
        assert seen == ["t0", "t1", "t2", "t3", "t4"]

    async def test_iter_since_respects_cutoff(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        now = datetime.now(tz=UTC)
        await rec.record(_make_trace("old", when=now - timedelta(hours=2)))
        await rec.record(_make_trace("new", when=now))
        seen = [t.trace_id async for t in rec.iter_since(now - timedelta(hours=1))]
        assert seen == ["new"]


# ---------------------------------------------------------------------------
# Vacuum + count + clear
# ---------------------------------------------------------------------------


class TestSqliteHousekeeping:
    async def test_vacuum_removes_old_traces(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        now = datetime.now(tz=UTC)
        await rec.record(_make_trace("old", when=now - timedelta(days=10)))
        await rec.record(_make_trace("new", when=now))
        removed = await rec.vacuum_older_than(now - timedelta(days=5))
        assert removed == 1
        assert await rec.count() == 1
        assert rec.get_by_id("old") is None
        assert rec.get_by_id("new") is not None

    async def test_count_initial_zero(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        assert await rec.count() == 0

    async def test_clear(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:")
        await rec.record(_make_trace("t1"))
        await rec.record(_make_trace("t2"))
        assert await rec.count() == 2
        await rec.clear()
        assert await rec.count() == 0

    async def test_max_traces_evicts_oldest(self) -> None:
        rec = SqliteAuditRecorder(path=":memory:", max_traces=3)
        now = datetime.now(tz=UTC)
        for i in range(5):
            await rec.record(_make_trace(f"t{i}", when=now + timedelta(seconds=i)))
        assert await rec.count() == 3
        # The three newest should remain.
        ids = {r.trace_id for r in rec.get_records(limit=10)}
        assert ids == {"t2", "t3", "t4"}


# ---------------------------------------------------------------------------
# In-memory recorder gained the same methods (parity)
# ---------------------------------------------------------------------------


class TestInMemoryParity:
    async def test_get_by_id(self) -> None:
        rec = AuditRecorder()
        await rec.record(_make_trace("t1"))
        assert rec.get_by_id("t1") is not None
        assert rec.get_by_id("missing") is None

    async def test_iter_since(self) -> None:
        rec = AuditRecorder()
        now = datetime.now(tz=UTC)
        await rec.record(_make_trace("old", when=now - timedelta(hours=2)))
        await rec.record(_make_trace("new", when=now))
        seen = [t.trace_id async for t in rec.iter_since(now - timedelta(hours=1))]
        assert seen == ["new"]

    async def test_vacuum(self) -> None:
        rec = AuditRecorder()
        now = datetime.now(tz=UTC)
        await rec.record(_make_trace("old", when=now - timedelta(days=10)))
        await rec.record(_make_trace("new", when=now))
        removed = await rec.vacuum_older_than(now - timedelta(days=5))
        assert removed == 1


# ---------------------------------------------------------------------------
# Use inside HarnessEngine
# ---------------------------------------------------------------------------


class TestHarnessEngineWithSqlite:
    @pytest.mark.asyncio
    async def test_harness_engine_accepts_sqlite_recorder(self) -> None:
        from agenticapi.harness import CodePolicy, HarnessEngine

        rec = SqliteAuditRecorder(path=":memory:")
        engine = HarnessEngine(audit_recorder=rec, policies=[CodePolicy()])
        assert engine.audit_recorder is rec
