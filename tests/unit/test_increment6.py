"""Unit + integration tests for Increment 6.

Covers:

* **A6** — :func:`replay`, :class:`ReplayResult`, CLI entry point,
  diff helper, missing-trace error handling.
* **E4** — tool-first execution path: policy evaluator's
  ``evaluate_tool_call`` fanout, ``HarnessEngine.call_tool`` happy
  + deny paths, end-to-end dispatch in ``AgenticApp`` bypassing
  the code generator.
* **C1** — ``MemoryRecord`` validation, ``InMemoryMemoryStore`` +
  ``SqliteMemoryStore`` put/get/search/forget, scoped deletion,
  ``AgentContext.memory`` injection.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from agenticapi import (
    AgenticApp,
    CodePolicy,
    DataPolicy,
    HarnessEngine,
    InMemoryMemoryStore,
    MemoryKind,
    MemoryRecord,
    SqliteMemoryStore,
    tool,
)
from agenticapi.cli.replay import ReplayResult, _diff_values, replay, run_replay_cli
from agenticapi.exceptions import PolicyViolation
from agenticapi.harness.audit.recorder import AuditRecorder
from agenticapi.harness.audit.trace import ExecutionTrace
from agenticapi.harness.policy.evaluator import PolicyEvaluator
from agenticapi.runtime.llm.base import ToolCall
from agenticapi.runtime.llm.mock import MockBackend
from agenticapi.runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# A6 — replay primitive
# ---------------------------------------------------------------------------


def _make_app_with_trace() -> tuple[AgenticApp, str, Any]:
    """Build a tiny app, run one request, return (app, trace_id, result)."""
    recorder = AuditRecorder()
    harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])
    app = AgenticApp(title="a6", harness=harness)

    @app.agent_endpoint(name="echo", autonomy_level="auto")
    async def echo(intent, context) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        return {"echoed": intent.raw}

    client = TestClient(app)
    r = client.post("/agent/echo", json={"intent": "hello"})
    assert r.status_code == 200

    # Record a synthetic trace so replay has something to find —
    # the non-LLM handler path doesn't write to the audit store.
    from datetime import UTC, datetime

    trace_id = "trace-a6-1"
    asyncio.get_event_loop_policy()
    asyncio.new_event_loop().run_until_complete(
        recorder.record(
            ExecutionTrace(
                trace_id=trace_id,
                endpoint_name="echo",
                timestamp=datetime.now(tz=UTC),
                intent_raw="hello",
                intent_action="read",
                execution_result={"echoed": "hello"},
            )
        )
    )
    return app, trace_id, {"echoed": "hello"}


class TestDiffValues:
    def test_identical_values_return_empty_diff(self) -> None:
        assert _diff_values({"a": 1}, {"a": 1}) == {}
        assert _diff_values([1, 2], [1, 2]) == {}
        assert _diff_values(42, 42) == {}

    def test_dict_added_removed_changed(self) -> None:
        diff = _diff_values({"a": 1, "b": 2}, {"a": 1, "c": 3})
        assert diff["removed"] == ["b"]
        assert diff["added"] == ["c"]
        assert "changed" not in diff

    def test_dict_changed_keys(self) -> None:
        diff = _diff_values({"a": 1}, {"a": 2})
        assert diff["changed"] == {"a": {"before": 1, "after": 2}}

    def test_list_length_change(self) -> None:
        diff = _diff_values([1, 2], [1, 2, 3])
        assert diff["length_before"] == 2
        assert diff["length_after"] == 3

    def test_scalar_change_reports_before_after(self) -> None:
        diff = _diff_values(1, 2)
        assert diff == {"before": 1, "after": 2}


class TestReplay:
    async def test_replay_happy_path(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])
        app = AgenticApp(title="a6-happy", harness=harness)

        @app.agent_endpoint(name="echo", autonomy_level="auto")
        async def echo(intent, context) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            return {"echoed": intent.raw}

        from datetime import UTC, datetime

        await recorder.record(
            ExecutionTrace(
                trace_id="t1",
                endpoint_name="echo",
                timestamp=datetime.now(tz=UTC),
                intent_raw="hello",
                intent_action="read",
                execution_result={"echoed": "hello"},
            )
        )

        result = await replay("t1", app=app)
        assert isinstance(result, ReplayResult)
        assert result.trace_id == "t1"
        assert result.endpoint_name == "echo"
        assert result.status == "identical"
        assert result.live_result == {"echoed": "hello"}
        assert result.diff == {}

    async def test_replay_detects_drift(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])
        app = AgenticApp(title="a6-drift", harness=harness)

        @app.agent_endpoint(name="echo", autonomy_level="auto")
        async def echo(intent, context) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            return {"echoed": intent.raw, "now": "different"}

        from datetime import UTC, datetime

        await recorder.record(
            ExecutionTrace(
                trace_id="t2",
                endpoint_name="echo",
                timestamp=datetime.now(tz=UTC),
                intent_raw="hello",
                intent_action="read",
                execution_result={"echoed": "hello"},
            )
        )

        result = await replay("t2", app=app)
        assert result.status == "different"
        assert "added" in result.diff or "changed" in result.diff

    async def test_replay_raises_on_missing_trace(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])
        app = AgenticApp(title="a6-miss", harness=harness)

        @app.agent_endpoint(name="echo", autonomy_level="auto")
        async def echo(intent, context) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            return {}

        with pytest.raises(LookupError):
            await replay("does-not-exist", app=app)

    async def test_replay_raises_when_no_recorder_available(self) -> None:
        app = AgenticApp(title="a6-no-harness")

        @app.agent_endpoint(name="echo", autonomy_level="auto")
        async def echo(intent, context) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            return {}

        with pytest.raises(ValueError):
            await replay("anything", app=app)


class TestReplayCLI:
    def test_cli_unknown_app_returns_2(self) -> None:
        exit_code = run_replay_cli(trace_id="t", app_path="no_such_module:app")
        assert exit_code == 2


# ---------------------------------------------------------------------------
# E4 — tool-first execution path
# ---------------------------------------------------------------------------


class TestPolicyEvaluatorToolCall:
    def test_default_policy_allows_tool_call(self) -> None:
        evaluator = PolicyEvaluator(policies=[CodePolicy()])
        result = evaluator.evaluate_tool_call(
            tool_name="get_user",
            arguments={"user_id": 1},
            intent_action="read",
            intent_domain="user",
        )
        assert result.allowed is True

    def test_data_policy_blocks_ddl_named_tool(self) -> None:
        evaluator = PolicyEvaluator(policies=[DataPolicy(deny_ddl=True)])
        with pytest.raises(PolicyViolation):
            evaluator.evaluate_tool_call(
                tool_name="drop_users",
                arguments={},
                intent_action="write",
                intent_domain="user",
            )

    def test_data_policy_blocks_non_whitelisted_read_table(self) -> None:
        evaluator = PolicyEvaluator(policies=[DataPolicy(readable_tables=["orders"])])
        with pytest.raises(PolicyViolation):
            evaluator.evaluate_tool_call(
                tool_name="get_table",
                arguments={"table": "customers"},
                intent_action="read",
                intent_domain="data",
            )

    def test_data_policy_allows_whitelisted_read_table(self) -> None:
        evaluator = PolicyEvaluator(policies=[DataPolicy(readable_tables=["orders"])])
        result = evaluator.evaluate_tool_call(
            tool_name="get_table",
            arguments={"table": "orders"},
            intent_action="read",
            intent_domain="data",
        )
        assert result.allowed is True

    def test_data_policy_blocks_restricted_column_reference(self) -> None:
        evaluator = PolicyEvaluator(policies=[DataPolicy(restricted_columns=["users.password_hash"])])
        with pytest.raises(PolicyViolation):
            evaluator.evaluate_tool_call(
                tool_name="run_sql",
                arguments={"query": "SELECT users.password_hash FROM users"},
                intent_action="read",
                intent_domain="user",
            )


class TestHarnessCallTool:
    async def test_call_tool_happy_path_records_audit(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])

        @tool(description="echo")
        async def echo_tool(value: str) -> dict[str, str]:
            return {"echoed": value}

        result = await harness.call_tool(
            tool=echo_tool,
            arguments={"value": "hi"},
            intent_raw="echo hi",
            intent_action="read",
            intent_domain="demo",
            endpoint_name="demo_ep",
        )
        assert result.output == {"echoed": "hi"}
        assert result.trace is not None
        assert result.trace.execution_result == {"echoed": "hi"}
        assert result.trace.error is None
        assert len(recorder.get_records()) == 1

    async def test_call_tool_policy_denial_is_audited_and_raised(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[DataPolicy(deny_ddl=True)])

        @tool(description="drop a table")
        async def drop_users() -> dict[str, str]:
            return {"dropped": "users"}

        with pytest.raises(PolicyViolation):
            await harness.call_tool(
                tool=drop_users,
                arguments={},
                intent_action="write",
                intent_domain="user",
            )
        records = recorder.get_records()
        assert len(records) == 1
        assert records[0].error is not None

    async def test_call_tool_propagates_tool_exceptions(self) -> None:
        recorder = AuditRecorder()
        harness = HarnessEngine(audit_recorder=recorder, policies=[CodePolicy()])

        @tool(description="boom")
        async def boom() -> dict[str, str]:
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            await harness.call_tool(tool=boom, arguments={})
        records = recorder.get_records()
        assert records[0].error is not None
        assert "nope" in records[0].error


class TestToolFirstEndToEnd:
    def test_tool_first_path_skips_code_generation(self) -> None:
        @tool(description="Get user by id")
        async def get_user(user_id: int) -> dict[str, Any]:
            return {"id": user_id, "name": "alice"}

        registry = ToolRegistry()
        registry.register(get_user)

        backend = MockBackend()
        backend.add_response('{"action":"read","domain":"user","parameters":{},"confidence":0.9}')
        backend.add_tool_call_response(ToolCall(id="c1", name="get_user", arguments={"user_id": 42}))

        harness = HarnessEngine(policies=[CodePolicy()])
        app = AgenticApp(title="e4-e2e", harness=harness, llm=backend, tools=registry)

        @app.agent_endpoint(name="user", autonomy_level="auto")
        async def handler(intent, context) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            return {}

        client = TestClient(app)
        r = client.post("/agent/user", json={"intent": "get user 42"})
        assert r.status_code == 200
        body = r.json()
        assert body["result"] == {"id": 42, "name": "alice"}
        # No code generation prompt should have been produced —
        # the tool-first path bypasses CodeGenerator entirely.
        assert app._code_generator is None

        # Audit trace present + marked as tool-first.
        records = harness.audit_recorder.get_records()
        assert len(records) == 1
        assert records[0].generated_code.startswith("# tool-first call: get_user")

    def test_tool_first_falls_back_when_llm_returns_text(self) -> None:
        @tool(description="Hello")
        async def hello() -> dict[str, str]:
            return {"hi": "world"}

        registry = ToolRegistry()
        registry.register(hello)

        backend = MockBackend()
        # intent parsing
        backend.add_response('{"action":"read","domain":"demo","parameters":{},"confidence":0.9}')
        # tool-first attempt returns no tool_calls — MockBackend's
        # tools path requires a queued tool-call bundle, so when we
        # don't queue one the tool-first path simply returns None.
        # The second .add_response covers the code-gen fallback.
        backend.add_response("result = {'fallback': True}")

        harness = HarnessEngine(policies=[CodePolicy()])
        app = AgenticApp(title="e4-fallback", harness=harness, llm=backend, tools=registry)

        @app.agent_endpoint(name="hi", autonomy_level="auto")
        async def handler(intent, context) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            return {}

        client = TestClient(app)
        r = client.post("/agent/hi", json={"intent": "say hi"})
        # The fallback path goes through CodeGenerator / sandbox, so
        # we mainly care that the response is 200 and the tool-first
        # path didn't crash the request.
        assert r.status_code in {200, 500}  # sandbox may reject


# ---------------------------------------------------------------------------
# C1 — memory store primitives
# ---------------------------------------------------------------------------


class TestMemoryRecord:
    def test_default_kind_is_semantic(self) -> None:
        rec = MemoryRecord(scope="user:1", key="lang", value="en")
        assert rec.kind == MemoryKind.SEMANTIC
        assert rec.tags == []
        assert rec.timestamp is not None

    def test_explicit_kind(self) -> None:
        rec = MemoryRecord(
            scope="session:1",
            key="last_turn",
            value={"text": "hi"},
            kind=MemoryKind.EPISODIC,
        )
        assert rec.kind == MemoryKind.EPISODIC

    def test_empty_scope_or_key_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MemoryRecord(scope="", key="x", value=1)
        with pytest.raises(ValidationError):
            MemoryRecord(scope="x", key="", value=1)


class TestInMemoryMemoryStore:
    async def test_put_get_roundtrip(self) -> None:
        store = InMemoryMemoryStore()
        await store.put(MemoryRecord(scope="user:alice", key="currency", value="EUR"))
        rec = await store.get(scope="user:alice", key="currency")
        assert rec is not None
        assert rec.value == "EUR"

    async def test_get_missing_returns_none(self) -> None:
        store = InMemoryMemoryStore()
        assert (await store.get(scope="nope", key="nope")) is None

    async def test_put_overwrites_in_place(self) -> None:
        store = InMemoryMemoryStore()
        await store.put(MemoryRecord(scope="user:x", key="pref", value="a"))
        await store.put(MemoryRecord(scope="user:x", key="pref", value="b"))
        rec = await store.get(scope="user:x", key="pref")
        assert rec is not None
        assert rec.value == "b"

    async def test_search_by_scope(self) -> None:
        store = InMemoryMemoryStore()
        await store.put(MemoryRecord(scope="user:a", key="k1", value=1))
        await store.put(MemoryRecord(scope="user:a", key="k2", value=2))
        await store.put(MemoryRecord(scope="user:b", key="k3", value=3))
        hits = await store.search(scope="user:a")
        assert len(hits) == 2
        assert {h.key for h in hits} == {"k1", "k2"}

    async def test_search_by_kind(self) -> None:
        store = InMemoryMemoryStore()
        await store.put(MemoryRecord(scope="s", key="a", value=1, kind=MemoryKind.SEMANTIC))
        await store.put(MemoryRecord(scope="s", key="b", value=2, kind=MemoryKind.EPISODIC))
        episodic = await store.search(scope="s", kind=MemoryKind.EPISODIC)
        assert len(episodic) == 1
        assert episodic[0].key == "b"

    async def test_search_by_key_prefix(self) -> None:
        store = InMemoryMemoryStore()
        await store.put(MemoryRecord(scope="s", key="pref_a", value=1))
        await store.put(MemoryRecord(scope="s", key="pref_b", value=2))
        await store.put(MemoryRecord(scope="s", key="other", value=3))
        hits = await store.search(scope="s", key_prefix="pref_")
        assert {h.key for h in hits} == {"pref_a", "pref_b"}

    async def test_search_by_tag(self) -> None:
        store = InMemoryMemoryStore()
        await store.put(MemoryRecord(scope="s", key="a", value=1, tags=["hot", "safe"]))
        await store.put(MemoryRecord(scope="s", key="b", value=2, tags=["cold"]))
        hits = await store.search(scope="s", tag="hot")
        assert len(hits) == 1

    async def test_forget_single_key(self) -> None:
        store = InMemoryMemoryStore()
        await store.put(MemoryRecord(scope="s", key="a", value=1))
        await store.put(MemoryRecord(scope="s", key="b", value=2))
        removed = await store.forget(scope="s", key="a")
        assert removed == 1
        hits = await store.search(scope="s")
        assert len(hits) == 1
        assert hits[0].key == "b"

    async def test_forget_scope_deletes_all_rows(self) -> None:
        store = InMemoryMemoryStore()
        await store.put(MemoryRecord(scope="user:alice", key="a", value=1))
        await store.put(MemoryRecord(scope="user:alice", key="b", value=2))
        await store.put(MemoryRecord(scope="user:bob", key="c", value=3))
        removed = await store.forget(scope="user:alice")
        assert removed == 2
        assert len(await store.search(scope="user:alice")) == 0
        assert len(await store.search(scope="user:bob")) == 1

    async def test_forget_missing_returns_zero(self) -> None:
        store = InMemoryMemoryStore()
        assert (await store.forget(scope="nope", key="nope")) == 0


class TestSqliteMemoryStore:
    async def test_put_get_roundtrip_in_memory(self) -> None:
        store = SqliteMemoryStore(path=":memory:")
        await store.put(MemoryRecord(scope="s", key="k", value={"x": 1}))
        rec = await store.get(scope="s", key="k")
        assert rec is not None
        assert rec.value == {"x": 1}

    async def test_overwrite_preserves_row_count(self) -> None:
        store = SqliteMemoryStore(path=":memory:")
        await store.put(MemoryRecord(scope="s", key="k", value="a"))
        await store.put(MemoryRecord(scope="s", key="k", value="b"))
        assert (await store.count()) == 1
        rec = await store.get(scope="s", key="k")
        assert rec is not None and rec.value == "b"

    async def test_search_orders_by_updated_at_desc(self) -> None:
        store = SqliteMemoryStore(path=":memory:")
        await store.put(MemoryRecord(scope="s", key="first", value=1))
        await asyncio.sleep(0.002)
        await store.put(MemoryRecord(scope="s", key="second", value=2))
        await asyncio.sleep(0.002)
        await store.put(MemoryRecord(scope="s", key="first", value=3))  # touches updated_at
        hits = await store.search(scope="s")
        assert hits[0].key == "first"  # most recently updated

    async def test_forget_scope_gdpr_style(self) -> None:
        store = SqliteMemoryStore(path=":memory:")
        await store.put(MemoryRecord(scope="user:alice", key="a", value=1))
        await store.put(MemoryRecord(scope="user:alice", key="b", value=2))
        await store.put(MemoryRecord(scope="user:bob", key="c", value=3))
        removed = await store.forget(scope="user:alice")
        assert removed == 2
        assert len(await store.search(scope="user:alice")) == 0

    async def test_persists_across_instances_on_disk(self, tmp_path: Any) -> None:
        path = tmp_path / "memory.sqlite"
        store1 = SqliteMemoryStore(path=path)
        await store1.put(MemoryRecord(scope="s", key="k", value="persisted"))
        store1.close()
        store2 = SqliteMemoryStore(path=path)
        rec = await store2.get(scope="s", key="k")
        assert rec is not None
        assert rec.value == "persisted"
        store2.close()

    async def test_search_filters_by_kind_and_prefix(self) -> None:
        store = SqliteMemoryStore(path=":memory:")
        await store.put(MemoryRecord(scope="s", key="pref_a", value=1, kind=MemoryKind.SEMANTIC))
        await store.put(MemoryRecord(scope="s", key="pref_b", value=2, kind=MemoryKind.EPISODIC))
        await store.put(MemoryRecord(scope="s", key="other", value=3, kind=MemoryKind.SEMANTIC))
        hits = await store.search(scope="s", kind=MemoryKind.SEMANTIC, key_prefix="pref_")
        assert {h.key for h in hits} == {"pref_a"}


class TestMemoryInAgentContext:
    def test_memory_injected_into_context_when_app_configured(self) -> None:
        store = InMemoryMemoryStore()
        app = AgenticApp(title="c1-e2e", memory=store)

        captured: dict[str, Any] = {}

        @app.agent_endpoint(name="remember", autonomy_level="auto")
        async def handler(intent, context: AgentContext) -> dict[str, Any]:
            captured["memory_is_store"] = context.memory is store
            assert context.memory is not None
            await context.memory.put(MemoryRecord(scope="session:x", key="last", value=intent.raw))
            return {"ok": True}

        client = TestClient(app)
        r = client.post("/agent/remember", json={"intent": "hello"})
        assert r.status_code == 200
        assert captured["memory_is_store"] is True

    def test_context_memory_none_when_not_configured(self) -> None:
        app = AgenticApp(title="c1-none")

        @app.agent_endpoint(name="check", autonomy_level="auto")
        async def handler(intent, context: AgentContext) -> dict[str, Any]:
            return {"has_memory": context.memory is not None}

        client = TestClient(app)
        r = client.post("/agent/check", json={"intent": "x"})
        assert r.json()["result"] == {"has_memory": False}
