"""Tests for the trace inspector routes and mounting."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starlette.testclient import TestClient

from agenticapi.app import AgenticApp
from agenticapi.harness.audit.trace import ExecutionTrace
from agenticapi.harness.engine import HarnessEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(trace_url: str | None = "/_trace") -> AgenticApp:
    harness = HarnessEngine()
    app = AgenticApp(title="Test App", harness=harness, trace_url=trace_url)

    @app.agent_endpoint(name="hello", description="A test endpoint")
    async def hello(intent: Any, context: Any) -> dict[str, str]:
        return {"message": "Hello!"}

    return app


def _inject_trace(app: AgenticApp, trace_id: str, intent: str = "test", endpoint: str = "hello") -> None:
    """Directly inject a trace into the app's in-memory audit recorder."""
    trace = ExecutionTrace(
        trace_id=trace_id,
        endpoint_name=endpoint,
        timestamp=datetime.now(tz=UTC),
        intent_raw=intent,
        intent_action="read",
        execution_duration_ms=42.5,
    )
    # Directly append to the in-memory store (bypassing async record()).
    recorder = app._harness.audit_recorder  # type: ignore[union-attr]
    recorder._traces.append(trace)


# ---------------------------------------------------------------------------
# Mounting tests
# ---------------------------------------------------------------------------


class TestTraceInspectorMount:
    def test_trace_ui_served_when_enabled(self) -> None:
        app = _make_app(trace_url="/_trace")
        client = TestClient(app)
        r = client.get("/_trace")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Trace Inspector" in r.text

    def test_trace_returns_404_when_disabled(self) -> None:
        app = _make_app(trace_url=None)
        client = TestClient(app)
        r = client.get("/_trace")
        assert r.status_code in (404, 405)

    def test_custom_trace_url(self) -> None:
        app = _make_app(trace_url="/debug/traces")
        client = TestClient(app)
        r = client.get("/debug/traces")
        assert r.status_code == 200
        assert "Trace Inspector" in r.text

    def test_health_still_works(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Search API tests
# ---------------------------------------------------------------------------


class TestTraceSearch:
    def test_search_empty(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_trace/api/search")
        assert r.status_code == 200
        data = r.json()
        assert data["traces"] == []
        assert data["total"] == 0

    def test_search_returns_traces(self) -> None:
        app = _make_app()
        _inject_trace(app, "t1", intent="test search", endpoint="hello")
        client = TestClient(app)
        r = client.get("/_trace/api/search")
        data = r.json()
        assert data["total"] >= 1
        assert data["traces"][0]["endpoint"] == "hello"

    def test_search_filter_by_status(self) -> None:
        app = _make_app()
        _inject_trace(app, "t2", intent="test")
        client = TestClient(app)
        r = client.get("/_trace/api/search?status=success")
        assert r.json()["total"] >= 1
        r = client.get("/_trace/api/search?status=error")
        assert r.json()["total"] == 0

    def test_search_no_harness(self) -> None:
        app = AgenticApp(title="No Harness", trace_url="/_trace")

        @app.agent_endpoint(name="hi")
        async def hi(intent: Any, context: Any) -> dict[str, str]:
            return {"msg": "hi"}

        client = TestClient(app)
        r = client.get("/_trace/api/search")
        assert r.status_code == 200
        assert r.json()["total"] == 0


# ---------------------------------------------------------------------------
# Detail API tests
# ---------------------------------------------------------------------------


class TestTraceDetail:
    def test_detail_not_found(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_trace/api/traces/nonexistent")
        assert r.status_code == 404

    def test_detail_returns_trace(self) -> None:
        app = _make_app()
        _inject_trace(app, "detail-1", intent="detail test")
        client = TestClient(app)
        r = client.get("/_trace/api/traces/detail-1")
        assert r.status_code == 200
        data = r.json()
        assert data["trace_id"] == "detail-1"
        assert "timeline" in data


# ---------------------------------------------------------------------------
# Diff API tests
# ---------------------------------------------------------------------------


class TestTraceDiff:
    def test_diff_missing_params(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_trace/api/diff")
        assert r.status_code == 400

    def test_diff_not_found(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_trace/api/diff?a=x&b=y")
        assert r.status_code == 404

    def test_diff_two_traces(self) -> None:
        app = _make_app()
        _inject_trace(app, "diff-a", intent="diff test 1")
        _inject_trace(app, "diff-b", intent="diff test 2")
        client = TestClient(app)
        r = client.get("/_trace/api/diff?a=diff-a&b=diff-b")
        assert r.status_code == 200
        data = r.json()
        assert data["trace_a"] == "diff-a"
        assert data["trace_b"] == "diff-b"
        assert isinstance(data["changed"], list)
        # Intent text differs.
        intent_changes = [c for c in data["changed"] if c["field"] == "intent_text"]
        assert len(intent_changes) == 1

    def test_diff_identical_traces(self) -> None:
        app = _make_app()
        _inject_trace(app, "same-a", intent="same")
        _inject_trace(app, "same-b", intent="same")
        client = TestClient(app)
        r = client.get("/_trace/api/diff?a=same-a&b=same-b")
        data = r.json()
        # Only trace_id differs (not compared in diff), so changed should
        # be empty for the fields we compare.
        assert data["identical"] is True


# ---------------------------------------------------------------------------
# Stats API tests
# ---------------------------------------------------------------------------


class TestTraceStats:
    def test_stats_empty(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_trace/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["total_traces"] == 0

    def test_stats_with_data(self) -> None:
        app = _make_app()
        _inject_trace(app, "stat-1")
        _inject_trace(app, "stat-2")
        client = TestClient(app)
        r = client.get("/_trace/api/stats")
        data = r.json()
        assert data["total_traces"] == 2
        assert "by_endpoint" in data
        assert "by_status" in data
        assert data["by_status"].get("success", 0) == 2


# ---------------------------------------------------------------------------
# Export API tests
# ---------------------------------------------------------------------------


class TestTraceExport:
    def test_export_not_found(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_trace/api/export/nonexistent")
        assert r.status_code == 404

    def test_export_returns_json(self) -> None:
        app = _make_app()
        _inject_trace(app, "export-1", intent="export test")
        client = TestClient(app)
        r = client.get("/_trace/api/export/export-1")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")
        data = r.json()
        assert data["report_type"] == "agenticapi_trace_export"
        assert data["trace"]["trace_id"] == "export-1"
