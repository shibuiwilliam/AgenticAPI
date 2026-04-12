"""Unit + integration tests for Increment 5 streaming additions.

Covers:

* **F6** — :class:`AutonomyPolicy` rule evaluation, monotonic
  escalation, :class:`AutonomyState` event emission, end-to-end
  integration with a streaming endpoint and the audit recorder.
* **F3** — NDJSON transport frame format, content type, end-to-end
  via ``TestClient``, ordering and terminal events.
* **F7** — :class:`InMemoryStreamStore` append/get_after/wait/
  mark_complete, ``tail_from`` drains then terminates on complete,
  the framework mirrors stream events into the store, and the
  ``GET /agent/{name}/stream/{stream_id}`` resume route replays.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.testclient import TestClient

from agenticapi import (
    AgenticApp,
    AgentStream,
    AutonomyLevel,
    AutonomyPolicy,
    AutonomySignal,
    EscalateWhen,
)
from agenticapi.harness import AuditRecorder, CodePolicy, HarnessEngine
from agenticapi.harness.policy.autonomy_policy import AutonomyState
from agenticapi.interface.stream import AutonomyChangedEvent
from agenticapi.interface.stream_store import (
    InMemoryStreamStore,
    event_to_dict,
    tail_from,
)
from agenticapi.interface.transports.ndjson import (
    event_to_ndjson_frame,
    run_ndjson_response,
)

# ---------------------------------------------------------------------------
# F6 — AutonomyPolicy + EscalateWhen
# ---------------------------------------------------------------------------


class TestAutonomyPolicy:
    def test_rule_matches_confidence_below(self) -> None:
        rule = EscalateWhen(confidence_below=0.7, level=AutonomyLevel.SUPERVISED)
        assert rule.matches(AutonomySignal(confidence=0.6))
        assert not rule.matches(AutonomySignal(confidence=0.8))
        assert not rule.matches(AutonomySignal())  # confidence=None never matches

    def test_rule_matches_cost_above(self) -> None:
        rule = EscalateWhen(cost_usd_above=0.2, level=AutonomyLevel.SUPERVISED)
        assert rule.matches(AutonomySignal(cost_usd=0.3))
        assert not rule.matches(AutonomySignal(cost_usd=0.1))
        assert not rule.matches(AutonomySignal(cost_usd=0.2))  # strict >

    def test_rule_matches_policy_flagged(self) -> None:
        rule = EscalateWhen(policy_flagged=True, level=AutonomyLevel.MANUAL)
        assert rule.matches(AutonomySignal(policy_flagged=True))
        assert not rule.matches(AutonomySignal(policy_flagged=False))

    def test_rule_matches_novelty_above(self) -> None:
        rule = EscalateWhen(novelty_above=0.5, level=AutonomyLevel.SUPERVISED)
        assert rule.matches(AutonomySignal(novelty=0.7))
        assert not rule.matches(AutonomySignal(novelty=0.3))

    def test_rule_all_conditions_must_match(self) -> None:
        rule = EscalateWhen(
            confidence_below=0.7,
            cost_usd_above=0.1,
            level=AutonomyLevel.MANUAL,
        )
        assert rule.matches(AutonomySignal(confidence=0.5, cost_usd=0.2))
        assert not rule.matches(AutonomySignal(confidence=0.5, cost_usd=0.05))
        assert not rule.matches(AutonomySignal(confidence=0.9, cost_usd=0.2))

    def test_resolve_picks_strictest_matching_rule(self) -> None:
        policy = AutonomyPolicy(
            start=AutonomyLevel.AUTO,
            rules=[
                EscalateWhen(confidence_below=0.8, level=AutonomyLevel.SUPERVISED),
                EscalateWhen(confidence_below=0.8, level=AutonomyLevel.MANUAL),
            ],
        )
        new_level, rule = policy.resolve(AutonomyLevel.AUTO, AutonomySignal(confidence=0.5))
        assert new_level == AutonomyLevel.MANUAL
        assert rule is not None
        assert rule.level == AutonomyLevel.MANUAL

    def test_resolve_no_match_returns_current(self) -> None:
        policy = AutonomyPolicy(
            start=AutonomyLevel.AUTO,
            rules=[EscalateWhen(confidence_below=0.5, level=AutonomyLevel.SUPERVISED)],
        )
        new_level, rule = policy.resolve(AutonomyLevel.AUTO, AutonomySignal(confidence=0.9))
        assert new_level == AutonomyLevel.AUTO
        assert rule is None

    def test_resolve_monotonic_ignores_downward_rule(self) -> None:
        """A rule that would move the level *down* must be ignored."""
        policy = AutonomyPolicy(
            start=AutonomyLevel.MANUAL,
            rules=[EscalateWhen(confidence_below=1.0, level=AutonomyLevel.AUTO)],
        )
        new_level, rule = policy.resolve(AutonomyLevel.MANUAL, AutonomySignal(confidence=0.1))
        assert new_level == AutonomyLevel.MANUAL  # unchanged
        assert rule is None  # downward attempt discarded

    def test_synthesised_reason_fallbacks(self) -> None:
        rule = EscalateWhen(confidence_below=0.7, level=AutonomyLevel.SUPERVISED)
        reason = rule.synthesised_reason(AutonomySignal(confidence=0.5))
        assert "confidence" in reason

        rule_with_reason = EscalateWhen(
            cost_usd_above=0.1,
            level=AutonomyLevel.SUPERVISED,
            reason="explicit override",
        )
        assert rule_with_reason.synthesised_reason(AutonomySignal(cost_usd=0.3)) == "explicit override"


class TestAutonomyState:
    async def test_observe_transitions_and_emits(self) -> None:
        transitions: list[tuple[str, str, str]] = []

        async def capture(
            *, previous: AutonomyLevel, current: AutonomyLevel, reason: str, signal: AutonomySignal
        ) -> None:
            del signal
            transitions.append((previous.value, current.value, reason))

        policy = AutonomyPolicy(
            start=AutonomyLevel.AUTO,
            rules=[
                EscalateWhen(confidence_below=0.7, level=AutonomyLevel.SUPERVISED),
                EscalateWhen(policy_flagged=True, level=AutonomyLevel.MANUAL),
            ],
        )
        state = AutonomyState(policy=policy, emit_change=capture)
        assert state.current_level == AutonomyLevel.AUTO

        # No-op signal.
        assert (await state.observe(AutonomySignal(confidence=0.9))) == AutonomyLevel.AUTO
        assert transitions == []

        # First escalation.
        assert (await state.observe(AutonomySignal(confidence=0.6))) == AutonomyLevel.SUPERVISED
        assert transitions == [("auto", "supervised", "confidence 0.60 < 0.7")]

        # Second escalation.
        assert (await state.observe(AutonomySignal(policy_flagged=True))) == AutonomyLevel.MANUAL
        assert transitions[-1] == ("supervised", "manual", "policy flagged")

        # Downward signal is silently ignored.
        assert (await state.observe(AutonomySignal(confidence=0.99))) == AutonomyLevel.MANUAL
        assert len(transitions) == 2  # no new transition

    async def test_history_records_every_transition(self) -> None:
        policy = AutonomyPolicy(
            start=AutonomyLevel.AUTO,
            rules=[EscalateWhen(confidence_below=0.7, level=AutonomyLevel.SUPERVISED)],
        )
        state = AutonomyState(policy=policy)
        await state.observe(AutonomySignal(confidence=0.5))
        assert len(state.history) == 1
        assert state.history[0]["previous"] == "auto"
        assert state.history[0]["current"] == "supervised"
        assert "reason" in state.history[0]
        assert "signal" in state.history[0]


class TestAgentStreamAutonomy:
    async def test_report_signal_emits_autonomy_changed_event(self) -> None:
        policy = AutonomyPolicy(
            start=AutonomyLevel.AUTO,
            rules=[EscalateWhen(confidence_below=0.7, level=AutonomyLevel.SUPERVISED)],
        )
        stream = AgentStream(stream_id="s1", autonomy=policy)
        assert stream.current_autonomy_level == "auto"

        level = await stream.report_signal(confidence=0.6)
        assert level == "supervised"
        assert stream.current_autonomy_level == "supervised"

        kinds = [e.kind for e in stream.emitted_events]
        assert "autonomy_changed" in kinds
        event = next(e for e in stream.emitted_events if e.kind == "autonomy_changed")
        assert isinstance(event, AutonomyChangedEvent)
        assert event.previous == "auto"
        assert event.current == "supervised"

    async def test_report_signal_without_policy_is_safe_noop(self) -> None:
        stream = AgentStream(stream_id="s1")
        level = await stream.report_signal(confidence=0.1, policy_flagged=True)
        assert level == "auto"
        assert stream.current_autonomy_level == "auto"
        assert not any(e.kind == "autonomy_changed" for e in stream.emitted_events)

    async def test_autonomy_history_exposed_on_stream(self) -> None:
        policy = AutonomyPolicy(
            start=AutonomyLevel.AUTO,
            rules=[
                EscalateWhen(confidence_below=0.7, level=AutonomyLevel.SUPERVISED),
                EscalateWhen(policy_flagged=True, level=AutonomyLevel.MANUAL),
            ],
        )
        stream = AgentStream(stream_id="s1", autonomy=policy)
        await stream.report_signal(confidence=0.5)
        await stream.report_signal(policy_flagged=True)
        assert len(stream.autonomy_history) == 2
        assert stream.autonomy_history[0]["current"] == "supervised"
        assert stream.autonomy_history[1]["current"] == "manual"


class TestAutonomyEndpointIntegration:
    def test_endpoint_with_autonomy_policy_emits_events_and_audits(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])
        app = AgenticApp(title="f6", harness=harness)

        policy = AutonomyPolicy(
            start=AutonomyLevel.AUTO,
            rules=[EscalateWhen(confidence_below=0.7, level=AutonomyLevel.SUPERVISED)],
        )

        @app.agent_endpoint(name="analytics", autonomy=policy, streaming="sse")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            await stream.emit_thought("planning")
            level = await stream.report_signal(confidence=0.6)
            return {"level": level}

        client = TestClient(app)
        with client.stream("POST", "/agent/analytics", json={"intent": "run"}) as r:
            assert r.status_code == 200
            body = "".join(chunk for chunk in r.iter_text())

        assert "event: autonomy_changed" in body
        assert '"current":"supervised"' in body or '"current": "supervised"' in body

        trace = recorder.get_records()[0]
        kinds = [event["kind"] for event in trace.stream_events]
        assert "autonomy_changed" in kinds
        assert kinds[-1] == "final"  # terminal event still last


# ---------------------------------------------------------------------------
# F3 — NDJSON transport
# ---------------------------------------------------------------------------


class TestNDJSONFrameFormat:
    def test_frame_is_single_line_terminated_json(self) -> None:
        from agenticapi.interface.stream import ThoughtEvent

        event = ThoughtEvent(text="hi", seq=0, timestamp="2026-01-01T00:00:00+00:00")
        frame = event_to_ndjson_frame(event).decode("utf-8")
        assert frame.endswith("\n")
        # Exactly one newline.
        assert frame.count("\n") == 1
        payload = json.loads(frame.strip())
        assert payload["kind"] == "thought"
        assert payload["text"] == "hi"
        assert payload["seq"] == 0


class TestNDJSONEndpoint:
    def test_streaming_endpoint_returns_application_x_ndjson(self) -> None:
        app = AgenticApp(title="f3")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="ndjson")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            await stream.emit_thought("a")
            await stream.emit_partial({"row": 1})
            return {"done": True}

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("application/x-ndjson")
            body = "".join(chunk for chunk in r.iter_text())

        # Parse every non-empty line (heartbeats are bare newlines).
        events = [json.loads(line) for line in body.splitlines() if line.strip()]
        kinds = [event["kind"] for event in events]
        assert kinds == ["thought", "partial_result", "final"]
        # Seqs are monotonic.
        seqs = [event["seq"] for event in events]
        assert seqs == sorted(seqs)
        assert seqs[0] == 0

    def test_streaming_endpoint_handles_exceptions_as_error_events(self) -> None:
        app = AgenticApp(title="f3-err")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="ndjson")
        async def handler(intent, context, stream: AgentStream) -> None:
            await stream.emit_thought("about to fail")
            raise ValueError("boom")

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            body = "".join(chunk for chunk in r.iter_text())

        events = [json.loads(line) for line in body.splitlines() if line.strip()]
        kinds = [e["kind"] for e in events]
        assert "thought" in kinds
        assert "error" in kinds
        err = next(e for e in events if e["kind"] == "error")
        assert err["error_kind"] == "ValueError"

    async def test_run_ndjson_response_returns_streaming_response(self) -> None:
        # Unit-level smoke test on run_ndjson_response directly so we
        # don't depend on Starlette's TestClient behaviour for this bit.
        stream = AgentStream(stream_id="s1")

        async def factory() -> str:
            await stream.emit_thought("hi")
            return "ok"

        response = await run_ndjson_response(
            stream=stream,
            handler_task_factory=factory,
            heartbeat_interval=60.0,
        )
        assert response.media_type == "application/x-ndjson"
        assert response.headers["cache-control"] == "no-cache, no-transform"


# ---------------------------------------------------------------------------
# F7 — StreamStore + resume route
# ---------------------------------------------------------------------------


class TestInMemoryStreamStore:
    async def test_append_and_get_after(self) -> None:
        store = InMemoryStreamStore()
        await store.append("s1", {"kind": "thought", "seq": 0, "text": "a"})
        await store.append("s1", {"kind": "thought", "seq": 1, "text": "b"})
        await store.append("s1", {"kind": "thought", "seq": 2, "text": "c"})

        all_events = await store.get_after("s1", -1)
        assert [e["seq"] for e in all_events] == [0, 1, 2]

        tail_events = await store.get_after("s1", 0)
        assert [e["seq"] for e in tail_events] == [1, 2]

    async def test_wait_wakes_on_append(self) -> None:
        store = InMemoryStreamStore()

        async def producer() -> None:
            await asyncio.sleep(0.02)
            await store.append("s1", {"kind": "thought", "seq": 0})

        task = asyncio.create_task(producer())
        await store.wait("s1", timeout=1.0)
        events = await store.get_after("s1", -1)
        assert len(events) == 1
        await task

    async def test_wait_times_out_cleanly(self) -> None:
        store = InMemoryStreamStore()
        # No producer — wait should return on timeout without raising.
        await store.wait("s1", timeout=0.05)
        events = await store.get_after("s1", -1)
        assert events == []

    async def test_mark_complete_wakes_waiters(self) -> None:
        store = InMemoryStreamStore()
        woken = asyncio.Event()

        async def waiter() -> None:
            await store.wait("s1", timeout=5.0)
            woken.set()

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.01)
        await store.mark_complete("s1")
        try:
            await asyncio.wait_for(woken.wait(), timeout=1.0)
        finally:
            await task
        assert await store.is_complete("s1") is True

    async def test_discard_removes_stream(self) -> None:
        store = InMemoryStreamStore()
        await store.append("s1", {"kind": "thought", "seq": 0})
        await store.discard("s1")
        events = await store.get_after("s1", -1)
        assert events == []

    async def test_tail_from_drains_and_exits_on_complete(self) -> None:
        store = InMemoryStreamStore()
        await store.append("s1", {"kind": "thought", "seq": 0})
        await store.append("s1", {"kind": "partial_result", "seq": 1})
        await store.append("s1", {"kind": "final", "seq": 2})
        await store.mark_complete("s1")

        seen: list[dict[str, Any]] = []
        async for event in tail_from(store, "s1", since_seq=-1):
            seen.append(event)
        assert [e["seq"] for e in seen] == [0, 1, 2]

    async def test_tail_from_respects_since_seq(self) -> None:
        store = InMemoryStreamStore()
        for seq in range(5):
            await store.append("s1", {"kind": "thought", "seq": seq})
        await store.mark_complete("s1")

        seen: list[int] = []
        async for event in tail_from(store, "s1", since_seq=1):
            seen.append(int(event["seq"]))
        assert seen == [2, 3, 4]

    async def test_tail_from_picks_up_late_append_before_complete(self) -> None:
        store = InMemoryStreamStore()
        await store.append("s1", {"kind": "thought", "seq": 0})

        async def producer() -> None:
            await asyncio.sleep(0.02)
            await store.append("s1", {"kind": "partial_result", "seq": 1})
            await asyncio.sleep(0.02)
            await store.append("s1", {"kind": "final", "seq": 2})
            await store.mark_complete("s1")

        producer_task = asyncio.create_task(producer())

        seen: list[int] = []
        async for event in tail_from(store, "s1", since_seq=-1, wait_timeout=0.1):
            seen.append(int(event["seq"]))
        await producer_task
        assert seen == [0, 1, 2]


class TestAgentStreamPersistsToStore:
    async def test_emit_mirrors_to_store(self) -> None:
        store = InMemoryStreamStore()
        stream = AgentStream(stream_id="s1", stream_store=store)
        await stream.emit_thought("hello")
        await stream.emit_partial({"row": 1})
        events = await store.get_after("s1", -1)
        kinds = [e["kind"] for e in events]
        assert kinds == ["thought", "partial_result"]

    async def test_close_marks_store_complete(self) -> None:
        store = InMemoryStreamStore()
        stream = AgentStream(stream_id="s1", stream_store=store)
        await stream.emit_thought("hi")
        await stream.close()
        assert await store.is_complete("s1") is True

    async def test_emit_after_close_does_not_append(self) -> None:
        store = InMemoryStreamStore()
        stream = AgentStream(stream_id="s1", stream_store=store)
        await stream.close()
        await stream.emit_thought("late")
        events = await store.get_after("s1", -1)
        assert events == []


class TestResumeRoute:
    def test_resume_route_404_for_unknown_stream(self) -> None:
        app = AgenticApp(title="f7")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="ndjson")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            return {"ok": True}

        client = TestClient(app)
        r = client.get("/agent/ep/stream/does-not-exist")
        assert r.status_code == 404
        payload = r.json()
        assert payload["status"] == "error"

    def test_resume_route_replays_completed_stream(self) -> None:
        """After running a streaming request, the resume route serves a replay."""
        app = AgenticApp(title="f7")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="ndjson")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            await stream.emit_thought("a")
            await stream.emit_thought("b")
            return {"done": True}

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            body = "".join(chunk for chunk in r.iter_text())

        live_events = [json.loads(line) for line in body.splitlines() if line.strip()]
        stream_id = live_events[0].get("seq") is not None  # sanity
        assert stream_id is True

        # Pull the stream_id from the app's store — a live client
        # would normally have received it via a prior exchange or via
        # a header. We can recover it from the audit trace if a
        # recorder is attached, but we don't attach one here, so
        # instead we use the store directly.
        store = app._stream_store
        # One stream expected.
        # ``_streams`` is private but it's the simplest way to get
        # at the stream_id the framework minted.
        stream_ids = list(store._streams.keys())
        assert len(stream_ids) == 1
        sid = stream_ids[0]

        r = client.get(f"/agent/ep/stream/{sid}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        replay_events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
        kinds = [e["kind"] for e in replay_events]
        assert kinds == ["thought", "thought", "final"]

    def test_resume_route_honours_since_query_param(self) -> None:
        app = AgenticApp(title="f7-since")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="ndjson")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            await stream.emit_thought("a")
            await stream.emit_thought("b")
            await stream.emit_thought("c")
            return {"done": True}

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            _ = "".join(chunk for chunk in r.iter_text())

        store = app._stream_store
        sid = next(iter(store._streams.keys()))

        r = client.get(f"/agent/ep/stream/{sid}?since=1")
        assert r.status_code == 200
        replay_events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
        # since=1 skips seq 0 and seq 1 and returns seq 2..N.
        seqs = [e["seq"] for e in replay_events]
        assert all(seq > 1 for seq in seqs)
        # The terminal final event must still appear last.
        assert replay_events[-1]["kind"] == "final"


class TestEventToDict:
    def test_event_to_dict_matches_model_dump(self) -> None:
        from agenticapi.interface.stream import ThoughtEvent

        event = ThoughtEvent(text="hi", seq=3, timestamp="2026-01-01T00:00:00+00:00")
        d = event_to_dict(event)
        assert d["kind"] == "thought"
        assert d["text"] == "hi"
        assert d["seq"] == 3


# ---------------------------------------------------------------------------
# Cross-increment regression check
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_legacy_endpoint_without_streaming_still_returns_json(self) -> None:
        app = AgenticApp(title="compat")

        @app.agent_endpoint(name="legacy", autonomy_level="auto")
        async def handler(intent, context) -> dict[str, Any]:
            return {"ok": True}

        client = TestClient(app)
        r = client.post("/agent/legacy", json={"intent": "x"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/json"

    def test_sse_endpoint_still_works_after_ndjson_addition(self) -> None:
        app = AgenticApp(title="compat-sse")

        @app.agent_endpoint(name="ep", autonomy_level="auto", streaming="sse")
        async def handler(intent, context, stream: AgentStream) -> dict[str, Any]:
            await stream.emit_thought("hello")
            return {"ok": True}

        client = TestClient(app)
        with client.stream("POST", "/agent/ep", json={"intent": "x"}) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            body = "".join(chunk for chunk in r.iter_text())
        assert "event: thought" in body
        assert "event: final" in body
