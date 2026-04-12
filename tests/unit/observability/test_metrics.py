"""Unit tests for ``agenticapi.observability.metrics``.

These run with OTEL not installed, so the tests verify the no-op
fallback works cleanly: every recording helper is callable, the
``/metrics`` endpoint serves a valid (empty) response, and
``configure_metrics`` doesn't raise.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from agenticapi import AgenticApp
from agenticapi.observability import (
    configure_metrics,
    is_metrics_available,
    record_budget_block,
    record_llm_usage,
    record_policy_denial,
    record_request,
    record_sandbox_violation,
    record_tool_call,
    render_prometheus_exposition,
)
from agenticapi.observability import metrics as metrics_module


@pytest.fixture(autouse=True)
def _reset_metrics():
    yield
    metrics_module.reset_for_tests()


class TestNoopRecordersWithoutOTEL:
    def test_metrics_unavailable(self) -> None:
        assert is_metrics_available() is False

    def test_all_recorders_callable(self) -> None:
        """Every recording helper is a no-op when metrics are not configured."""
        record_request(endpoint="ep", status="completed", duration_seconds=0.05)
        record_policy_denial(policy="CodePolicy", endpoint="ep")
        record_sandbox_violation(kind="memory", endpoint="ep")
        record_llm_usage(model="mock", input_tokens=10, output_tokens=20, cost_usd=0.001)
        record_tool_call(tool="db", endpoint="ep")
        record_budget_block(scope="session")
        # No exceptions = pass.

    def test_render_prometheus_returns_empty(self) -> None:
        body, content_type = render_prometheus_exposition()
        assert body == b""
        assert content_type.startswith("text/plain")

    def test_configure_metrics_warns_but_does_not_raise(self) -> None:
        configure_metrics(service_name="test")  # No exception.


class TestMetricsEndpointWiring:
    def test_metrics_url_registers_route(self) -> None:
        """Setting metrics_url registers a GET route returning 200."""
        app = AgenticApp(title="m-test", metrics_url="/metrics")

        @app.agent_endpoint(name="ep", autonomy_level="auto")
        async def handler(intent, context):
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200
        # Empty body in no-op mode is the expected behaviour.
        assert response.text == ""
        # Content type is the Prometheus text/plain variant.
        assert "text/plain" in response.headers["content-type"]

    def test_metrics_url_none_means_no_route(self) -> None:
        """The default (no metrics_url) registers no /metrics route."""
        app = AgenticApp(title="no-metrics")

        @app.agent_endpoint(name="ep", autonomy_level="auto")
        async def handler(intent, context):
            return {"ok": True}

        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 404

    def test_request_still_succeeds_with_metrics_enabled(self) -> None:
        """Wiring metrics in does not break request handling."""
        app = AgenticApp(title="m-test", metrics_url="/metrics")

        @app.agent_endpoint(name="orders.query", autonomy_level="auto")
        async def handler(intent, context):
            return {"orders": [1, 2, 3]}

        client = TestClient(app)
        body = client.post("/agent/orders.query", json={"intent": "show"}).json()
        assert body["status"] == "completed"
        assert body["result"] == {"orders": [1, 2, 3]}
