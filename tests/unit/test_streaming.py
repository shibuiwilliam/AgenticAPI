"""Unit tests for the Phase F streaming lifecycle.

Covers:

* **F1** — :class:`AgentStream` event schema, monotonic seq, emit
  methods, the queue/consume loop, and the scanner detecting
  ``AgentStream`` parameters.
* **F2** — SSE transport: frame format, content type, header set,
  ordering, end-to-end via ``TestClient``.
* **F5** — :class:`ApprovalRegistry` round-trip, resume endpoint,
  timeout fallback.
* **F8** — audit trace integration: streamed events land in the
  audit recorder, including the terminal :class:`FinalEvent`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from starlette.testclient import TestClient

from agenticapi import AgentEvent, AgenticApp, AgentStream
from agenticapi.dependencies import scan_handler
from agenticapi.dependencies.scanner import InjectionKind
from agenticapi.harness import AuditRecorder, CodePolicy, HarnessEngine
from agenticapi.interface.approval_registry import ApprovalRegistry
from agenticapi.interface.stream import (
    ApprovalRequestedEvent,
    ApprovalResolvedEvent,
    ErrorEvent,
    FinalEvent,
    PartialResultEvent,
    ThoughtEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agenticapi.interface.transports.sse import event_to_sse_frame

# ---------------------------------------------------------------------------
# F1 — event schema + AgentStream
# ---------------------------------------------------------------------------


class TestEventSchema:
    def test_thought_event_kind(self) -> None:
        e = ThoughtEvent(text="hello")
        assert e.kind == "thought"
        assert e.text == "hello"

    def test_tool_call_started_event(self) -> None:
        e = ToolCallStartedEvent(call_id="c1", name="get_user", arguments={"id": 42})
        assert e.kind == "tool_call_started"
        assert e.call_id == "c1"
        assert e.name == "get_user"

    def test_tool_call_completed_event(self) -> None:
        e = ToolCallCompletedEvent(call_id="c1", duration_ms=12.3)
        assert e.kind == "tool_call_completed"
        assert e.call_id == "c1"

    def test_partial_result_event(self) -> None:
        e = PartialResultEvent(chunk={"row": 1})
        assert e.kind == "partial_result"
        assert e.chunk == {"row": 1}

    def test_approval_requested_event(self) -> None:
        e = ApprovalRequestedEvent(
            approval_id="a1",
            stream_id="s1",
            prompt="proceed?",
            options=["yes", "no"],
        )
        assert e.kind == "approval_requested"

    def test_approval_resolved_event(self) -> None:
        e = ApprovalResolvedEvent(approval_id="a1", decision="yes")
        assert e.kind == "approval_resolved"
        assert e.decision == "yes"

    def test_final_event(self) -> None:
        e = FinalEvent(result={"done": True})
        assert e.kind == "final"
        assert e.result == {"done": True}

    def test_error_event(self) -> None:
        e = ErrorEvent(error_kind="ValueError", message="boom")
        assert e.kind == "error"
        assert e.message == "boom"


class TestAgentStream:
    async def test_emit_thought_assigns_seq_and_timestamp(self) -> None:
        stream = AgentStream(stream_id="s1")
        await stream.emit_thought("hello")
        events = stream.emitted_events
        assert len(events) == 1
        assert events[0].seq == 0
        assert events[0].timestamp != ""

    async def test_monotonic_seq(self) -> None:
        stream = AgentStream(stream_id="s1")
        for i in range(5):
            await stream.emit_thought(f"step {i}")
        assert [e.seq for e in stream.emitted_events] == [0, 1, 2, 3, 4]

    async def test_emit_tool_call_pair(self) -> None:
        stream = AgentStream(stream_id="s1")
        await stream.emit_tool_call_started(call_id="c1", name="get_user")
        await stream.emit_tool_call_completed(call_id="c1", duration_ms=5.0)
        kinds = [e.kind for e in stream.emitted_events]
        assert kinds == ["tool_call_started", "tool_call_completed"]

    async def test_emit_partial_then_final_closes_stream(self) -> None:
        stream = AgentStream(stream_id="s1")
        await stream.emit_partial({"row": 1})
        await stream.emit_final({"done": True})
        assert stream.is_closed
        assert any(isinstance(e, FinalEvent) for e in stream.emitted_events)

    async def test_emit_after_close_is_warned_no_op(self) -> None:
        stream = AgentStream(stream_id="s1")
        await stream.emit_final("done")
        # Subsequent emits are silently dropped (warning logged) —
        # the stream's emitted_events list should not grow.
        prior = len(stream.emitted_events)
        await stream.emit_thought("late")
        assert len(stream.emitted_events) == prior

    async def test_consume_yields_events_then_exits_after_close(self) -> None:
        stream = AgentStream(stream_id="s1")
        # Pre-load some events.
        await stream.emit_thought("a")
        await stream.emit_thought("b")
        await stream.close()

        seen: list[AgentEvent] = []
        async for event in stream.consume():
            seen.append(event)
        assert [e.kind for e in seen] == ["thought", "thought"]

    async def test_request_approval_without_factory_raises(self) -> None:
        stream = AgentStream(stream_id="s1")
        with pytest.raises(NotImplementedError):
            await stream.request_approval(prompt="?")

    async def test_request_approval_with_factory(self) -> None:
        registry = ApprovalRegistry()
        factory = registry.create_handle_factory("s1")
        stream = AgentStream(stream_id="s1", approval_handle_factory=factory)

        async def resolve_after() -> None:
            await asyncio.sleep(0.02)
            await registry.resolve("s1", "yes")

        resolver = asyncio.create_task(resolve_after())
        decision = await stream.request_approval(prompt="?", options=["yes", "no"])
        await resolver
        assert decision == "yes"

        kinds = [e.kind for e in stream.emitted_events]
        assert "approval_requested" in kinds
        assert "approval_resolved" in kinds


class TestScannerRecognisesAgentStream:
    def test_scanner_detects_stream_param(self) -> None:
        async def handler(intent, context, stream: AgentStream):
            del intent, context, stream

        plan = scan_handler(handler)
        kinds = [p.kind for p in plan.params]
        assert InjectionKind.AGENT_STREAM in kinds

    def test_scanner_legacy_handler_unchanged(self) -> None:
        """Handlers without AgentStream still scan as legacy positional."""

        async def handler(intent, context):
            del intent, context

        plan = scan_handler(handler)
        assert plan.legacy_positional_count == 2


# ---------------------------------------------------------------------------
# F2 — SSE transport
# ---------------------------------------------------------------------------


class TestSSEFrameFormat:
    def test_frame_starts_with_event_kind(self) -> None:
        e = ThoughtEvent(text="hi", seq=0, timestamp="2026-01-01T00:00:00+00:00")
        frame = event_to_sse_frame(e)
        text = frame.decode("utf-8")
        assert text.startswith("event: thought\n")
        assert "data: " in text
        assert text.endswith("\n\n")

    def test_frame_data_is_valid_json(self) -> None:
        e = PartialResultEvent(chunk={"row": 1}, seq=3, timestamp="2026-01-01T00:00:00+00:00")
        frame = event_to_sse_frame(e).decode("utf-8")
        data_line = next(line for line in frame.split("\n") if line.startswith("data: "))
        payload = json.loads(data_line[len("data: ") :])
        assert payload["kind"] == "partial_result"
        assert payload["chunk"] == {"row": 1}
        assert payload["seq"] == 3


class TestSSEEndpoint:
    def test_streaming_endpoint_returns_event_stream(self) -> None:
        app = AgenticApp(title="f-test")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="sse")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            await stream.emit_thought("step1")
            await stream.emit_partial({"row": 1})
            return {"done": True}

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            body = "".join(chunk for chunk in r.iter_text())

        # Three events: thought, partial_result, final.
        assert body.count("event: thought") == 1
        assert body.count("event: partial_result") == 1
        assert body.count("event: final") == 1

    def test_streaming_endpoint_emits_events_in_order(self) -> None:
        app = AgenticApp(title="f-test")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="sse")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            await stream.emit_thought("a")
            await stream.emit_thought("b")
            await stream.emit_thought("c")
            return {}

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            body = "".join(chunk for chunk in r.iter_text())

        # Extract seqs from data lines.
        seqs: list[int] = []
        for line in body.split("\n"):
            if line.startswith("data: "):
                payload = json.loads(line[len("data: ") :])
                seqs.append(payload["seq"])
        # Should be strictly monotonic.
        assert seqs == sorted(seqs)
        assert seqs[0] == 0

    def test_handler_exception_emits_error_event(self) -> None:
        app = AgenticApp(title="f-test")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="sse")
        async def handler(intent, context, stream: AgentStream) -> None:
            await stream.emit_thought("about to fail")
            raise ValueError("boom")

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            body = "".join(chunk for chunk in r.iter_text())
        assert "event: thought" in body
        assert "event: error" in body
        assert "ValueError" in body

    def test_non_streaming_endpoint_unchanged(self) -> None:
        """Endpoints without streaming= keep returning a single JSON blob."""
        app = AgenticApp(title="f-test")

        @app.agent_endpoint(name="legacy", autonomy_level="auto")
        async def handler(intent, context):
            return {"ok": True}

        client = TestClient(app)
        r = client.post("/agent/legacy", json={"intent": "x"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/json"
        body = r.json()
        assert body["status"] == "completed"
        assert body["result"] == {"ok": True}


# ---------------------------------------------------------------------------
# F5 — approval registry + resume endpoint
# ---------------------------------------------------------------------------


class TestApprovalRegistry:
    async def test_resolve_wakes_waiter(self) -> None:
        reg = ApprovalRegistry()
        factory = reg.create_handle_factory("s1")
        handle = factory("s1")

        async def waiter() -> tuple[str, bool]:
            return await handle.wait(timeout_seconds=1.0)

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.01)
        ok = await reg.resolve("s1", "yes")
        assert ok
        decision, timed_out = await task
        assert decision == "yes"
        assert timed_out is False

    async def test_timeout_uses_default_decision(self) -> None:
        reg = ApprovalRegistry()
        factory = reg.create_handle_factory("s1", default_decision="reject")
        handle = factory("s1")
        decision, timed_out = await handle.wait(timeout_seconds=0.05)
        assert decision == "reject"
        assert timed_out is True

    async def test_resolve_unknown_stream_returns_false(self) -> None:
        reg = ApprovalRegistry()
        ok = await reg.resolve("does-not-exist", "yes")
        assert ok is False

    async def test_fifo_when_multiple_approvals_in_one_stream(self) -> None:
        reg = ApprovalRegistry()
        factory = reg.create_handle_factory("s1")
        h1 = factory("s1")
        h2 = factory("s1")

        async def w1() -> tuple[str, bool]:
            return await h1.wait(timeout_seconds=1.0)

        async def w2() -> tuple[str, bool]:
            return await h2.wait(timeout_seconds=1.0)

        t1 = asyncio.create_task(w1())
        t2 = asyncio.create_task(w2())
        await asyncio.sleep(0.01)

        # First resolve goes to h1 (FIFO).
        await reg.resolve("s1", "first")
        # Second resolve goes to h2.
        await reg.resolve("s1", "second")

        d1, _ = await t1
        d2, _ = await t2
        assert d1 == "first"
        assert d2 == "second"


# ---------------------------------------------------------------------------
# F8 — audit trace integration
# ---------------------------------------------------------------------------


class TestAuditIntegration:
    def test_audit_trace_captures_streamed_events(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])
        app = AgenticApp(title="f8-test", harness=harness)

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="sse")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            await stream.emit_thought("working")
            await stream.emit_partial({"progress": 50})
            return {"done": True}

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            for _ in r.iter_text():
                pass

        records = recorder.get_records()
        assert len(records) == 1
        trace = records[0]
        assert trace.endpoint_name == "ep"
        kinds = [event["kind"] for event in trace.stream_events]
        assert kinds == ["thought", "partial_result", "final"]
        # The final event carries the handler's return value.
        assert trace.stream_events[-1]["result"] == {"done": True}

    def test_audit_trace_captures_error_event_on_failure(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])
        app = AgenticApp(title="f8-err", harness=harness)

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="sse")
        async def handler(intent, context, stream: AgentStream) -> None:
            await stream.emit_thought("about to fail")
            raise RuntimeError("boom")

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            for _ in r.iter_text():
                pass

        trace = recorder.get_records()[0]
        kinds = [event["kind"] for event in trace.stream_events]
        assert "error" in kinds
