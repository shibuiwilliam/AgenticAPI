"""Tests for AuditRecorder."""

from __future__ import annotations

from datetime import UTC, datetime

from agenticapi.harness.audit.recorder import AuditRecorder
from agenticapi.harness.audit.trace import ExecutionTrace


def _make_trace(
    *,
    trace_id: str = "t1",
    endpoint_name: str = "test",
    intent_action: str = "read",
) -> ExecutionTrace:
    return ExecutionTrace(
        trace_id=trace_id,
        endpoint_name=endpoint_name,
        timestamp=datetime.now(tz=UTC),
        intent_raw="test intent",
        intent_action=intent_action,
        generated_code="result = 1",
    )


class TestAuditRecorderRecord:
    async def test_record_stores_trace(self) -> None:
        recorder = AuditRecorder()
        trace = _make_trace()
        await recorder.record(trace)
        records = recorder.get_records()
        assert len(records) == 1
        assert records[0].trace_id == "t1"

    async def test_record_multiple(self) -> None:
        recorder = AuditRecorder()
        await recorder.record(_make_trace(trace_id="t1"))
        await recorder.record(_make_trace(trace_id="t2"))
        await recorder.record(_make_trace(trace_id="t3"))
        assert len(recorder.get_records()) == 3


class TestAuditRecorderGetRecords:
    async def test_filters_by_endpoint_name(self) -> None:
        recorder = AuditRecorder()
        await recorder.record(_make_trace(trace_id="t1", endpoint_name="orders"))
        await recorder.record(_make_trace(trace_id="t2", endpoint_name="products"))
        await recorder.record(_make_trace(trace_id="t3", endpoint_name="orders"))

        records = recorder.get_records(endpoint_name="orders")
        assert len(records) == 2
        assert all(r.endpoint_name == "orders" for r in records)

    async def test_respects_limit(self) -> None:
        recorder = AuditRecorder()
        for i in range(20):
            await recorder.record(_make_trace(trace_id=f"t{i}"))

        records = recorder.get_records(limit=5)
        assert len(records) == 5

    async def test_most_recent_first(self) -> None:
        recorder = AuditRecorder()
        await recorder.record(_make_trace(trace_id="first"))
        await recorder.record(_make_trace(trace_id="second"))
        await recorder.record(_make_trace(trace_id="third"))

        records = recorder.get_records()
        assert records[0].trace_id == "third"
        assert records[-1].trace_id == "first"

    async def test_empty_recorder_returns_empty_list(self) -> None:
        recorder = AuditRecorder()
        assert recorder.get_records() == []

    async def test_filter_by_nonexistent_endpoint(self) -> None:
        recorder = AuditRecorder()
        await recorder.record(_make_trace())
        assert recorder.get_records(endpoint_name="nonexistent") == []


class TestAuditRecorderClear:
    async def test_clear_removes_all(self) -> None:
        recorder = AuditRecorder()
        await recorder.record(_make_trace(trace_id="t1"))
        await recorder.record(_make_trace(trace_id="t2"))
        recorder.clear()
        assert recorder.get_records() == []


class TestAuditRecorderBounds:
    async def test_max_traces_evicts_oldest(self) -> None:
        recorder = AuditRecorder(max_traces=3)
        await recorder.record(_make_trace(trace_id="t1"))
        await recorder.record(_make_trace(trace_id="t2"))
        await recorder.record(_make_trace(trace_id="t3"))
        await recorder.record(_make_trace(trace_id="t4"))

        records = recorder.get_records()
        assert len(records) == 3
        # t1 should be evicted
        trace_ids = [r.trace_id for r in records]
        assert "t1" not in trace_ids
        assert "t4" in trace_ids
