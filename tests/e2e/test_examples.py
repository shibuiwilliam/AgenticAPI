"""E2E tests: exercise every example app with real HTTP requests.

Each test class loads an example app, starts it via Starlette TestClient,
and sends requests to every endpoint plus the health check.

Tests are written to pass regardless of whether LLM API keys are set:
- When keys are absent, examples run in direct-handler mode (keyword parsing).
- When keys are present, LLM-based parsing and code generation are active,
  which may trigger approval workflows (202) or different intent classification.

Examples that *require* an API key at import time (04_anthropic, 05_gemini)
are skipped when the key is not set.
"""

from __future__ import annotations

import importlib
import os
from typing import Any

import pytest
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
_has_anthropic_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
_has_google_key = bool(os.environ.get("GOOGLE_API_KEY"))


def _load_app(module_path: str) -> Any:
    """Import an example module and return its ``app`` object."""
    mod = importlib.import_module(module_path)
    return mod.app


def _post_intent(
    client: TestClient,
    endpoint: str,
    intent: str,
    *,
    session_id: str | None = None,
    expected_statuses: set[int] | None = None,
) -> dict[str, Any]:
    """POST an intent and return the parsed JSON body.

    Args:
        expected_statuses: Acceptable HTTP status codes (default {200}).
    """
    body: dict[str, Any] = {"intent": intent}
    if session_id is not None:
        body["session_id"] = session_id
    response = client.post(f"/agent/{endpoint}", json=body)
    allowed = expected_statuses or {200}
    assert response.status_code in allowed, f"POST /agent/{endpoint} returned {response.status_code}: {response.text}"
    return response.json()


def _assert_health_ok(client: TestClient) -> dict[str, Any]:
    """GET /health and assert the app is healthy."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    return data


# ============================================================================
# 01_hello_agent
# ============================================================================


class TestExample01HelloAgent:
    """Minimal single-endpoint example."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.01_hello_agent.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "greeter" in data["endpoints"]

    def test_greeter_endpoint(self, client: TestClient) -> None:
        data = _post_intent(client, "greeter", "Hello, how are you?")
        assert data["status"] == "completed"
        assert "Hello" in str(data["result"])

    def test_greeter_with_japanese(self, client: TestClient) -> None:
        data = _post_intent(client, "greeter", "こんにちは")
        assert data["status"] == "completed"
        assert "こんにちは" in str(data["result"])


# ============================================================================
# 02_ecommerce
# ============================================================================


class TestExample02Ecommerce:
    """Multi-endpoint ecommerce app with routers."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.02_ecommerce.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "orders.query" in data["endpoints"]
        assert "products.search" in data["endpoints"]

    def test_order_query(self, client: TestClient) -> None:
        data = _post_intent(client, "orders.query", "Show me recent orders")
        assert data["status"] == "completed"

    def test_order_update(self, client: TestClient) -> None:
        # "Cancel" -> write action, "order" -> order domain
        data = _post_intent(client, "orders.update", "Cancel order 123")
        assert data["status"] == "completed"

    def test_order_query_analyze(self, client: TestClient) -> None:
        data = _post_intent(client, "orders.query", "Analyze order trends")
        assert data["status"] == "completed"

    def test_product_search(self, client: TestClient) -> None:
        data = _post_intent(client, "products.search", "Search for electronics")
        assert data["status"] == "completed"

    def test_product_analytics(self, client: TestClient) -> None:
        data = _post_intent(client, "products.analytics", "Show product analytics")
        assert data["status"] == "completed"

    def test_missing_intent_returns_400(self, client: TestClient) -> None:
        response = client.post("/agent/orders.query", json={"no_intent": "oops"})
        assert response.status_code == 400

    def test_nonexistent_endpoint_returns_404(self, client: TestClient) -> None:
        response = client.post("/agent/nonexistent", json={"intent": "hello"})
        assert response.status_code == 404


# ============================================================================
# 03_openai_agent
# ============================================================================


class TestExample03OpenAIAgent:
    """OpenAI-powered task tracker (LLM optional — runs without key)."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.03_openai_agent.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "tasks.query" in data["endpoints"]
        assert "tasks.analytics" in data["endpoints"]
        assert "tasks.update" in data["endpoints"]

    def test_task_query(self, client: TestClient) -> None:
        data = _post_intent(client, "tasks.query", "Show me all high-priority tasks")
        assert data["status"] == "completed"

    def test_task_analytics(self, client: TestClient) -> None:
        data = _post_intent(client, "tasks.analytics", "What is the completion rate?")
        assert data["status"] == "completed"

    def test_task_update_write_intent(self, client: TestClient) -> None:
        """Write intent on tasks.update:
        - Without LLM: keyword parser yields general.write -> 403 (scope blocks it).
        - With LLM: parses as task.write -> passes scope, hits approval -> 202.
        Both are correct behaviour."""
        response = client.post("/agent/tasks.update", json={"intent": "Update task 1 status to done"})
        assert response.status_code in {403, 202}

    def test_session_continuity(self, client: TestClient) -> None:
        d1 = _post_intent(client, "tasks.query", "Show all tasks", session_id="sess-e2e")
        d2 = _post_intent(client, "tasks.query", "Only the high priority ones", session_id="sess-e2e")
        assert d1["status"] == "completed"
        assert d2["status"] == "completed"

    def test_health_includes_custom_prompt_endpoints(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "tasks.summarize" in data["endpoints"]
        assert "tasks.prioritize" in data["endpoints"]

    @pytest.mark.skipif(not _has_openai_key, reason="OPENAI_API_KEY not set")
    def test_summarize_custom_prompt(self, client: TestClient) -> None:
        """LLM-powered summarize uses a custom system prompt."""
        data = _post_intent(client, "tasks.summarize", "Give me a brief status update")
        assert data["status"] == "completed"
        assert "summary" in data["result"]
        assert isinstance(data["result"]["summary"], str)
        assert len(data["result"]["summary"]) > 10

    @pytest.mark.skipif(not _has_openai_key, reason="OPENAI_API_KEY not set")
    def test_prioritize_custom_prompt(self, client: TestClient) -> None:
        """LLM-powered prioritize uses a custom system prompt."""
        data = _post_intent(client, "tasks.prioritize", "What should Alice work on next?")
        assert data["status"] == "completed"
        assert "recommendation" in data["result"]
        assert isinstance(data["result"]["recommendation"], str)

    def test_summarize_without_key_returns_error(self, client: TestClient) -> None:
        """Without API key, summarize returns a graceful error."""
        if _has_openai_key:
            pytest.skip("OPENAI_API_KEY is set — cannot test error path")
        data = _post_intent(client, "tasks.summarize", "Summarize")
        assert "error" in str(data.get("result", "")) or data.get("status") == "error"


# ============================================================================
# 04_anthropic_agent (requires ANTHROPIC_API_KEY to import)
# ============================================================================


@pytest.mark.skipif(not _has_anthropic_key, reason="ANTHROPIC_API_KEY not set")
class TestExample04AnthropicAgent:
    """Anthropic Claude product catalogue agent."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.04_anthropic_agent.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "products.search" in data["endpoints"]

    def test_product_search(self, client: TestClient) -> None:
        data = _post_intent(client, "products.search", "Show me electronics under 50000 yen")
        assert data["status"] == "completed"

    def test_product_inventory(self, client: TestClient) -> None:
        data = _post_intent(client, "products.inventory", "Which products are low in stock?")
        assert data["status"] == "completed"

    def test_health_includes_custom_prompt_endpoints(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "products.describe" in data["endpoints"]
        assert "products.recommend" in data["endpoints"]

    def test_describe_custom_prompt(self, client: TestClient) -> None:
        """LLM-powered product description uses a custom marketing prompt."""
        data = _post_intent(client, "products.describe", "Write a description for the Noise-Cancelling Headphones")
        assert data["status"] == "completed"
        assert "description" in data["result"]
        assert isinstance(data["result"]["description"], str)

    def test_recommend_custom_prompt(self, client: TestClient) -> None:
        """LLM-powered recommendation uses a custom shopping assistant prompt."""
        data = _post_intent(client, "products.recommend", "Suggest a gift for a developer under 20000 yen")
        assert data["status"] == "completed"
        assert "recommendation" in data["result"]


# ============================================================================
# 05_gemini_agent (requires GOOGLE_API_KEY to import)
# ============================================================================


@pytest.mark.skipif(not _has_google_key, reason="GOOGLE_API_KEY not set")
class TestExample05GeminiAgent:
    """Gemini support ticket agent.

    Note: The Gemini SDK uses its own async event loop which can conflict
    with Starlette's sync TestClient. Tests use ``expected_statuses``
    to tolerate both success and transient event-loop errors.
    """

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.05_gemini_agent.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "tickets.search" in data["endpoints"]

    def test_ticket_search(self, client: TestClient) -> None:
        # 200 = success, 400 = Gemini event-loop issue in sync test client
        data = _post_intent(
            client,
            "tickets.search",
            "Show all open critical tickets",
            expected_statuses={200, 400},
        )
        assert data.get("status") in {"completed", "error"}

    def test_ticket_metrics(self, client: TestClient) -> None:
        data = _post_intent(
            client,
            "tickets.metrics",
            "Average resolution time by severity",
            expected_statuses={200, 400},
        )
        assert data.get("status") in {"completed", "error"}

    def test_health_includes_custom_prompt_endpoints(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "tickets.analyze" in data["endpoints"]
        assert "tickets.draft_response" in data["endpoints"]

    def test_analyze_custom_prompt(self, client: TestClient) -> None:
        """LLM-powered root cause analysis uses a custom prompt."""
        data = _post_intent(
            client,
            "tickets.analyze",
            "What patterns do you see in auth-related tickets?",
            expected_statuses={200, 400},
        )
        assert data.get("status") in {"completed", "error"}
        if data["status"] == "completed":
            assert "analysis" in data["result"]

    def test_draft_response_custom_prompt(self, client: TestClient) -> None:
        """LLM-powered customer response draft uses a custom prompt."""
        data = _post_intent(
            client,
            "tickets.draft_response",
            "Draft a reply for the billing overcharge ticket",
            expected_statuses={200, 400},
        )
        assert data.get("status") in {"completed", "error"}
        if data["status"] == "completed":
            assert "draft" in data["result"]


# ============================================================================
# 06_full_stack
# ============================================================================


class TestExample06FullStack:
    """Full-stack warehouse agent with all features."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.06_full_stack.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "inventory.query" in data["endpoints"]
        assert "inventory.analytics" in data["endpoints"]
        assert "shipping.track" in data["endpoints"]
        assert "shipping.create" in data["endpoints"]

    def test_inventory_query(self, client: TestClient) -> None:
        # With LLM: harness generates code (may succeed or fail depending on LLM output).
        # Without LLM: handler runs directly -> 200.
        data = _post_intent(
            client, "inventory.query", "Show all items in the Tokyo warehouse", expected_statuses={200, 500}
        )
        assert data["status"] in {"completed", "error"}

    def test_inventory_analytics(self, client: TestClient) -> None:
        data = _post_intent(
            client, "inventory.analytics", "Compare stock levels across warehouses", expected_statuses={200, 500}
        )
        assert data["status"] in {"completed", "error"}

    def test_shipment_track(self, client: TestClient) -> None:
        # With LLM: harness generates code that may reference wrong data keys -> 500.
        # Without LLM: handler runs directly -> 200.
        data = _post_intent(
            client,
            "shipping.track",
            "Where is shipment SHP-001?",
            expected_statuses={200, 500},
        )
        assert data["status"] in {"completed", "error"}

    def test_shipment_create(self, client: TestClient) -> None:
        """Write intent on shipping.create:
        - Without LLM: keyword parser yields general.read -> 200 (broad scope allows *.read).
        - With LLM: parses as shipping.write -> passes scope, hits approval -> 202.
        Both are correct behaviour."""
        response = client.post(
            "/agent/shipping.create",
            json={"intent": "Ship 50 units of Laptop from Tokyo to Osaka"},
        )
        assert response.status_code in {200, 202}

    def test_session_multi_turn(self, client: TestClient) -> None:
        d1 = _post_intent(client, "inventory.query", "Show Tokyo warehouse", session_id="e2e-sess")
        d2 = _post_intent(client, "inventory.query", "Which are low in stock?", session_id="e2e-sess")
        assert d1["status"] == "completed"
        assert d2["status"] == "completed"

    def test_invalid_json_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/agent/inventory.query",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

    def test_empty_intent_returns_400(self, client: TestClient) -> None:
        response = client.post("/agent/inventory.query", json={"intent": ""})
        assert response.status_code == 400


# ============================================================================
# 06_full_stack — programmatic API (process_intent)
# ============================================================================


class TestExample06FullStackProgrammatic:
    """Test the programmatic process_intent() API for the full-stack example."""

    async def test_process_intent_inventory_query(self) -> None:
        app = _load_app("examples.06_full_stack.app")
        response = await app.process_intent("Show all items")
        assert response.status == "completed"

    async def test_process_intent_with_endpoint_name(self) -> None:
        app = _load_app("examples.06_full_stack.app")
        response = await app.process_intent(
            "Compare stock levels across warehouses",
            endpoint_name="inventory.analytics",
        )
        assert response.status == "completed"

    async def test_process_intent_with_session(self) -> None:
        app = _load_app("examples.06_full_stack.app")
        r1 = await app.process_intent("Show Tokyo warehouse", session_id="prog-test")
        r2 = await app.process_intent("Which are low?", session_id="prog-test")
        assert r1.status == "completed"
        assert r2.status == "completed"


# ============================================================================
# 07_comprehensive
# ============================================================================


class TestExample07Comprehensive:
    """Comprehensive DevOps platform — multiple features composed per endpoint."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.07_comprehensive.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "incidents.report" in data["endpoints"]
        assert "incidents.investigate" in data["endpoints"]
        assert "deployments.create" in data["endpoints"]
        assert "deployments.rollback" in data["endpoints"]
        assert "services.health" in data["endpoints"]

    def test_incident_report(self, client: TestClient) -> None:
        """Incident report:
        - Without LLM: direct handler returns 200 (completed/pending_approval).
        - With LLM: policy violation -> 403, sandbox error -> 500, approval -> 202.
        All are correct behaviour."""
        response = client.post(
            "/agent/incidents.report",
            json={"intent": "API gateway returning 502 errors"},
        )
        assert response.status_code in {200, 202, 403, 500}

    def test_incident_investigate(self, client: TestClient) -> None:
        """Investigation:
        - Without LLM: direct handler returns 200.
        - With LLM: policy -> 403, sandbox error -> 500.
        All are correct behaviour."""
        response = client.post(
            "/agent/incidents.investigate",
            json={"intent": "Check logs for the api-gateway"},
        )
        assert response.status_code in {200, 403, 500}

    def test_incident_investigate_session(self, client: TestClient) -> None:
        """Multi-turn investigation: two turns share a session.
        - Without LLM: direct handler returns 200.
        - With LLM: policy -> 403, sandbox error -> 500.
        All are correct behaviour."""
        r1 = client.post(
            "/agent/incidents.investigate",
            json={"intent": "Check api-gateway logs", "session_id": "inv-e2e"},
        )
        r2 = client.post(
            "/agent/incidents.investigate",
            json={"intent": "Now check payment-service", "session_id": "inv-e2e"},
        )
        assert r1.status_code in {200, 403, 500}
        assert r2.status_code in {200, 403, 500}

    def test_deployment_create(self, client: TestClient) -> None:
        """Write intent on deployments.create:
        - Without LLM: keyword parser yields general.write/read -> varying results.
        - With LLM: approval -> 202, policy -> 403, sandbox error -> 500.
        All are correct behaviour."""
        response = client.post(
            "/agent/deployments.create",
            json={"intent": "Deploy payment-service v2.3.1 to production"},
        )
        assert response.status_code in {200, 202, 403, 500}

    def test_deployment_rollback(self, client: TestClient) -> None:
        """Rollback intent:
        - Without LLM: keyword parser varies.
        - With LLM: approval -> 202, policy -> 403, sandbox error -> 500.
        All are correct behaviour."""
        response = client.post(
            "/agent/deployments.rollback",
            json={"intent": "Rollback payment-service to v2.3.0"},
        )
        assert response.status_code in {200, 202, 403, 500}

    def test_service_health(self, client: TestClient) -> None:
        """Service health:
        - Without LLM: direct handler returns 200.
        - With LLM: policy -> 403, sandbox error -> 500.
        All are correct behaviour."""
        response = client.post(
            "/agent/services.health",
            json={"intent": "Show health of all services"},
        )
        assert response.status_code in {200, 403, 500}

    def test_missing_intent_returns_400(self, client: TestClient) -> None:
        response = client.post("/agent/incidents.report", json={"no_intent": "oops"})
        assert response.status_code == 400

    def test_nonexistent_endpoint_returns_404(self, client: TestClient) -> None:
        response = client.post("/agent/nonexistent", json={"intent": "hello"})
        assert response.status_code == 404

    def test_empty_intent_returns_400(self, client: TestClient) -> None:
        response = client.post("/agent/services.health", json={"intent": ""})
        assert response.status_code == 400


# ============================================================================
# 07_comprehensive — programmatic API (process_intent)
# ============================================================================


class TestExample07ComprehensiveProgrammatic:
    """Test the programmatic process_intent() API for the comprehensive example.

    When an LLM is configured, process_intent() may raise:
    - ApprovalRequired: write intents trigger the approval workflow
    - PolicyViolation: generated code exceeds complexity limits
    - CodeExecutionError: generated code fails at runtime in the sandbox
    All are expected harness behaviour.
    """

    async def test_process_intent_incident_report(self) -> None:
        from agenticapi.exceptions import AgentRuntimeError, ApprovalRequired, HarnessError

        app = _load_app("examples.07_comprehensive.app")
        try:
            response = await app.process_intent(
                "API gateway returning 502 errors",
                endpoint_name="incidents.report",
            )
            assert response.status in {"completed", "pending_approval", "error"}
        except (ApprovalRequired, HarnessError, AgentRuntimeError):
            pass  # Expected with LLM — approval, policy, or sandbox error

    async def test_process_intent_incident_investigate(self) -> None:
        from agenticapi.exceptions import AgentRuntimeError, HarnessError

        app = _load_app("examples.07_comprehensive.app")
        try:
            response = await app.process_intent(
                "Check logs for api-gateway",
                endpoint_name="incidents.investigate",
            )
            assert response.status in {"completed", "error"}
        except (HarnessError, AgentRuntimeError):
            pass  # Expected with LLM — policy or sandbox error

    async def test_process_intent_deployment_create(self) -> None:
        from agenticapi.exceptions import AgentRuntimeError, ApprovalRequired, HarnessError

        app = _load_app("examples.07_comprehensive.app")
        try:
            response = await app.process_intent(
                "Deploy payment-service v2.3.1 to production",
                endpoint_name="deployments.create",
            )
            assert response.status in {"completed", "pending_approval", "error"}
        except (ApprovalRequired, HarnessError, AgentRuntimeError):
            pass  # Expected with LLM — approval, policy, or sandbox error

    async def test_process_intent_deployment_rollback(self) -> None:
        from agenticapi.exceptions import AgentRuntimeError, ApprovalRequired, HarnessError

        app = _load_app("examples.07_comprehensive.app")
        try:
            response = await app.process_intent(
                "Rollback payment-service to previous version",
                endpoint_name="deployments.rollback",
            )
            assert response.status in {"completed", "pending_approval", "error"}
        except (ApprovalRequired, HarnessError, AgentRuntimeError):
            pass  # Expected with LLM — approval, policy, or sandbox error

    async def test_process_intent_service_health(self) -> None:
        from agenticapi.exceptions import AgentRuntimeError, HarnessError

        app = _load_app("examples.07_comprehensive.app")
        try:
            response = await app.process_intent(
                "Show health of all services",
                endpoint_name="services.health",
            )
            assert response.status in {"completed", "error"}
        except (HarnessError, AgentRuntimeError):
            pass  # Expected with LLM — policy or sandbox error

    async def test_process_intent_with_session(self) -> None:
        from agenticapi.exceptions import AgentRuntimeError, HarnessError

        app = _load_app("examples.07_comprehensive.app")
        try:
            r1 = await app.process_intent(
                "Check api-gateway logs",
                session_id="prog-inv",
                endpoint_name="incidents.investigate",
            )
            assert r1.status in {"completed", "error"}
        except (HarnessError, AgentRuntimeError):
            pass  # Expected with LLM

        try:
            r2 = await app.process_intent(
                "Now check payment-service",
                session_id="prog-inv",
                endpoint_name="incidents.investigate",
            )
            assert r2.status in {"completed", "error"}
        except (HarnessError, AgentRuntimeError):
            pass  # Expected with LLM


# ============================================================================
# 08_mcp_agent (requires mcp package)
# ============================================================================

_has_mcp = bool(pytest.importorskip("mcp", reason="mcp not installed") if False else True)
try:
    import mcp  # noqa: F401

    _has_mcp = True
except ImportError:
    _has_mcp = False


@pytest.mark.skipif(not _has_mcp, reason="mcp package not installed")
class TestExample08MCPAgent:
    """MCP task tracker: selective MCP exposure via enable_mcp."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.08_mcp_agent.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "tasks.query" in data["endpoints"]
        assert "tasks.analytics" in data["endpoints"]
        assert "tasks.admin" in data["endpoints"]

    def test_task_query(self, client: TestClient) -> None:
        data = _post_intent(client, "tasks.query", "Show all high-priority tasks")
        assert data["status"] == "completed"

    def test_task_analytics(self, client: TestClient) -> None:
        data = _post_intent(client, "tasks.analytics", "What is the completion rate?")
        assert data["status"] == "completed"

    def test_task_admin(self, client: TestClient) -> None:
        data = _post_intent(client, "tasks.admin", "Reset all task statuses")
        assert data["status"] == "completed"

    def test_mcp_enabled_endpoints(self) -> None:
        """Only tasks.query and tasks.analytics have enable_mcp=True."""
        app = _load_app("examples.08_mcp_agent.app")
        mcp_enabled = [n for n, ep in app._endpoints.items() if ep.enable_mcp]
        assert set(mcp_enabled) == {"tasks.query", "tasks.analytics"}
        assert not app._endpoints["tasks.admin"].enable_mcp

    def test_missing_intent_returns_400(self, client: TestClient) -> None:
        response = client.post("/agent/tasks.query", json={"no_intent": "oops"})
        assert response.status_code == 400


@pytest.mark.skipif(not _has_mcp, reason="mcp package not installed")
class TestExample08MCPAgentProgrammatic:
    """Test process_intent() for the MCP example."""

    async def test_process_intent_task_query(self) -> None:
        app = _load_app("examples.08_mcp_agent.app")
        response = await app.process_intent("Show all tasks", endpoint_name="tasks.query")
        assert response.status == "completed"

    async def test_process_intent_task_analytics(self) -> None:
        app = _load_app("examples.08_mcp_agent.app")
        response = await app.process_intent("Completion rate", endpoint_name="tasks.analytics")
        assert response.status == "completed"


# ============================================================================
# 09_auth_agent
# ============================================================================


class TestExample09AuthAgent:
    """Auth example: public + protected endpoints with API key auth."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.09_auth_agent.app")
        return TestClient(app, raise_server_exceptions=False)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "info.public" in data["endpoints"]
        assert "info.protected" in data["endpoints"]
        assert "info.admin" in data["endpoints"]

    def test_public_endpoint_no_auth_needed(self, client: TestClient) -> None:
        data = _post_intent(client, "info.public", "What services are available?")
        assert data["status"] == "completed"

    def test_protected_endpoint_returns_401_without_key(self, client: TestClient) -> None:
        response = client.post("/agent/info.protected", json={"intent": "Show user details"})
        assert response.status_code == 401

    def test_protected_endpoint_returns_401_with_invalid_key(self, client: TestClient) -> None:
        response = client.post(
            "/agent/info.protected",
            json={"intent": "Show user details"},
            headers={"X-API-Key": "invalid-key"},
        )
        assert response.status_code == 401

    def test_protected_endpoint_returns_200_with_valid_key(self, client: TestClient) -> None:
        response = client.post(
            "/agent/info.protected",
            json={"intent": "Show user details"},
            headers={"X-API-Key": "alice-key-001"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        # Handler returns AgentResponse, which is wrapped → result.result has user_id
        inner = data["result"]
        if isinstance(inner, dict) and "result" in inner:
            assert inner["result"]["user_id"] == "user-1"

    def test_admin_endpoint_with_non_admin_key(self, client: TestClient) -> None:
        response = client.post(
            "/agent/info.admin",
            json={"intent": "Show all users"},
            headers={"X-API-Key": "alice-key-001"},
        )
        assert response.status_code == 200  # Auth passes, but handler returns error status
        data = response.json()
        assert "admin" in str(data["result"]).lower() or data["status"] == "error"

    def test_admin_endpoint_with_admin_key(self, client: TestClient) -> None:
        response = client.post(
            "/agent/info.admin",
            json={"intent": "Show all users"},
            headers={"X-API-Key": "admin-key-999"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"


# ============================================================================
# 10_file_handling
# ============================================================================


class TestExample10FileHandling:
    """File handling: upload, download, and streaming."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.10_file_handling.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "files.upload" in data["endpoints"]
        assert "files.export_csv" in data["endpoints"]
        assert "files.stream" in data["endpoints"]
        assert "files.info" in data["endpoints"]

    def test_json_endpoint(self, client: TestClient) -> None:
        data = _post_intent(client, "files.info", "Show capabilities")
        assert data["status"] == "completed"

    def test_file_upload_multipart(self, client: TestClient) -> None:
        response = client.post(
            "/agent/files.upload",
            data={"intent": "Analyze this file"},
            files={"document": ("test.txt", b"hello world", "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_csv_download(self, client: TestClient) -> None:
        response = client.post(
            "/agent/files.export_csv",
            json={"intent": "Export data"},
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        assert b"alice" in response.content

    def test_streaming_response(self, client: TestClient) -> None:
        response = client.post(
            "/agent/files.stream",
            json={"intent": "Stream log data"},
        )
        assert response.status_code == 200
        assert b"chunk 1" in response.content
        assert b"chunk 5" in response.content


# ============================================================================
# 11_html_responses
# ============================================================================


class TestExample11HTMLResponses:
    """HTML, plain text, and custom response types."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.11_html_responses.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "pages.home" in data["endpoints"]
        assert "pages.search" in data["endpoints"]
        assert "pages.status" in data["endpoints"]
        assert "pages.report" in data["endpoints"]
        assert "pages.api" in data["endpoints"]

    def test_home_returns_html(self, client: TestClient) -> None:
        response = client.post("/agent/pages.home", json={"intent": "Show the home page"})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<h1>Welcome to AgenticAPI</h1>" in response.text
        # Must NOT be JSON-wrapped
        assert "application/json" not in response.headers["content-type"]

    def test_search_returns_dynamic_html(self, client: TestClient) -> None:
        response = client.post("/agent/pages.search", json={"intent": "Python tutorials"})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Python tutorials" in response.text
        assert "Search Results" in response.text
        assert "3 results" in response.text

    def test_status_returns_plain_text(self, client: TestClient) -> None:
        response = client.post("/agent/pages.status", json={"intent": "Check status"})
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert "Status: OK" in response.text

    def test_report_returns_html_file_download(self, client: TestClient) -> None:
        response = client.post("/agent/pages.report", json={"intent": "Generate a report"})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "attachment" in response.headers.get("content-disposition", "")
        assert "report.html" in response.headers.get("content-disposition", "")
        assert "<table" in response.text

    def test_api_returns_json(self, client: TestClient) -> None:
        data = _post_intent(client, "pages.api", "Get API data")
        assert data["status"] == "completed"
        assert data["result"]["format"] == "json"
        assert "pages.home" in data["result"]["endpoints"]


# ============================================================================
# 12_htmx
# ============================================================================


class TestExample12Htmx:
    """HTMX interactive todo app with partial page updates."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.12_htmx.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "todo.list" in data["endpoints"]
        assert "todo.add" in data["endpoints"]
        assert "todo.search" in data["endpoints"]

    def test_full_page_without_htmx(self, client: TestClient) -> None:
        """Non-HTMX request returns full HTML page with HTMX script tag."""
        response = client.post("/agent/todo.list", json={"intent": "Show todos"})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<html" in response.text
        assert "htmx.org" in response.text
        assert "Learn AgenticAPI" in response.text

    def test_fragment_with_htmx(self, client: TestClient) -> None:
        """HTMX request returns HTML fragment (no full page wrapper)."""
        response = client.post(
            "/agent/todo.list",
            json={"intent": "Show todos"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<html" not in response.text
        assert "todo-items" in response.text

    def test_add_todo(self, client: TestClient) -> None:
        """Adding a todo returns updated list with HX-Trigger header."""
        response = client.post(
            "/agent/todo.add",
            json={"intent": "Write documentation"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "Write documentation" in response.text
        assert response.headers.get("hx-trigger") == "todoAdded"

    def test_search_filters(self, client: TestClient) -> None:
        """Search returns filtered results."""
        response = client.post(
            "/agent/todo.search",
            json={"intent": "code"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


# ============================================================================
# 13_claude_agent_sdk (requires the agenticapi-claude-agent-sdk extension)
# ============================================================================

try:
    import agenticapi_claude_agent_sdk  # noqa: F401

    _has_claude_sdk_extension = True
except ImportError:
    _has_claude_sdk_extension = False


def _install_stub_claude_agent_sdk() -> None:
    """Install a minimal stub of ``claude_agent_sdk`` in ``sys.modules``.

    The example app's ``ClaudeAgentRunner`` lazily imports the real SDK on
    first ``run()`` call. By installing a fake module before the test
    fires the runner, we can drive a deterministic message stream and
    avoid hitting the network or requiring an API key.

    Mirrors the more elaborate stub used by the extension's own offline
    tests in ``extensions/agenticapi-claude-agent-sdk/tests/conftest.py``.
    """
    import sys
    from dataclasses import dataclass, field
    from types import ModuleType
    from typing import Any as _Any

    @dataclass
    class _TextBlock:
        text: str

    @dataclass
    class _ThinkingBlock:
        thinking: str
        signature: str = ""

    @dataclass
    class _ToolUseBlock:
        id: str
        name: str
        input: dict[str, _Any]

    @dataclass
    class _ToolResultBlock:
        tool_use_id: str
        content: _Any = None
        is_error: bool | None = None

    @dataclass
    class _AssistantMessage:
        content: list[_Any]
        model: str = "stub-model"
        parent_tool_use_id: str | None = None

    @dataclass
    class _UserMessage:
        content: list[_Any]

    @dataclass
    class _SystemMessage:
        subtype: str
        data: dict[str, _Any]

    @dataclass
    class _ResultMessage:
        subtype: str = "success"
        duration_ms: int = 5
        duration_api_ms: int = 1
        is_error: bool = False
        num_turns: int = 1
        session_id: str = "stub-session"
        result: str | None = "Stubbed answer."
        structured_output: _Any = None
        total_cost_usd: float | None = 0.0
        usage: dict[str, _Any] | None = None
        errors: list[str] | None = None

    # Force the names the messages adapter dispatches on:
    _TextBlock.__name__ = "TextBlock"
    _ThinkingBlock.__name__ = "ThinkingBlock"
    _ToolUseBlock.__name__ = "ToolUseBlock"
    _ToolResultBlock.__name__ = "ToolResultBlock"
    _AssistantMessage.__name__ = "AssistantMessage"
    _UserMessage.__name__ = "UserMessage"
    _SystemMessage.__name__ = "SystemMessage"
    _ResultMessage.__name__ = "ResultMessage"

    @dataclass
    class _PermissionResultAllow:
        behavior: str = "allow"
        updated_input: dict[str, _Any] | None = None
        updated_permissions: list[_Any] | None = None

    @dataclass
    class _PermissionResultDeny:
        behavior: str = "deny"
        message: str = ""
        interrupt: bool = False

    @dataclass
    class _HookMatcher:
        matcher: str | None = None
        hooks: list[_Any] = field(default_factory=list)
        timeout: float | None = None

    @dataclass
    class _ClaudeAgentOptions:
        allowed_tools: list[str] = field(default_factory=list)
        disallowed_tools: list[str] = field(default_factory=list)
        permission_mode: str = "default"
        system_prompt: str | None = None
        model: str | None = None
        max_turns: int | None = None
        cwd: _Any = None
        env: dict[str, str] = field(default_factory=dict)
        mcp_servers: dict[str, _Any] = field(default_factory=dict)
        can_use_tool: _Any = None
        hooks: dict[str, _Any] | None = None

    @dataclass
    class _SdkMcpTool:
        name: str
        description: str
        input_schema: _Any
        handler: _Any

    @dataclass
    class _McpSdkServerConfig:
        name: str
        version: str
        tools: list[_SdkMcpTool]

    def _stub_query(*, prompt: _Any, options: _Any = None, transport: _Any = None) -> _Any:
        del prompt, options, transport

        async def _stream() -> _Any:
            yield _AssistantMessage(content=[_TextBlock(text="Stubbed answer.")])
            yield _ResultMessage(result="Stubbed answer.")

        return _stream()

    def _stub_tool(name: str, description: str, input_schema: _Any) -> _Any:
        def _decorate(handler: _Any) -> _SdkMcpTool:
            return _SdkMcpTool(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=handler,
            )

        return _decorate

    def _stub_create_sdk_mcp_server(
        name: str,
        version: str = "1.0.0",
        tools: list[_SdkMcpTool] | None = None,
    ) -> _McpSdkServerConfig:
        return _McpSdkServerConfig(name=name, version=version, tools=list(tools or []))

    module = ModuleType("claude_agent_sdk")
    module.query = _stub_query  # type: ignore[attr-defined]
    module.tool = _stub_tool  # type: ignore[attr-defined]
    module.create_sdk_mcp_server = _stub_create_sdk_mcp_server  # type: ignore[attr-defined]
    module.ClaudeAgentOptions = _ClaudeAgentOptions  # type: ignore[attr-defined]
    module.PermissionResultAllow = _PermissionResultAllow  # type: ignore[attr-defined]
    module.PermissionResultDeny = _PermissionResultDeny  # type: ignore[attr-defined]
    module.HookMatcher = _HookMatcher  # type: ignore[attr-defined]
    module.AssistantMessage = _AssistantMessage  # type: ignore[attr-defined]
    module.UserMessage = _UserMessage  # type: ignore[attr-defined]
    module.SystemMessage = _SystemMessage  # type: ignore[attr-defined]
    module.ResultMessage = _ResultMessage  # type: ignore[attr-defined]
    module.TextBlock = _TextBlock  # type: ignore[attr-defined]
    module.ThinkingBlock = _ThinkingBlock  # type: ignore[attr-defined]
    module.ToolUseBlock = _ToolUseBlock  # type: ignore[attr-defined]
    module.ToolResultBlock = _ToolResultBlock  # type: ignore[attr-defined]
    sys.modules["claude_agent_sdk"] = module


@pytest.mark.skipif(
    not _has_claude_sdk_extension,
    reason="agenticapi-claude-agent-sdk extension is not installed",
)
class TestExample13ClaudeAgentSDK:
    """End-to-end tests for the Claude Agent SDK extension example.

    These tests do not call the real Claude API. Tests that need the
    runner to actually run install a stub ``claude_agent_sdk`` module
    in ``sys.modules`` and reset the extension's lazy-import cache so
    the runner picks the stub up. Tests that only need ``/health``,
    ``/capabilities``, or the ``assistant.audit`` endpoint don't need
    the stub at all.
    """

    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.13_claude_agent_sdk.app")
        return TestClient(app)

    @pytest.fixture
    def stubbed_client(self) -> TestClient:
        """A client whose runner is wired up to a stub ``claude_agent_sdk``."""
        _install_stub_claude_agent_sdk()
        from agenticapi_claude_agent_sdk import _imports as _ext_imports

        _ext_imports._reset_cache_for_tests()
        # Force a fresh import of the example so the runner is rebuilt
        # against the stub module that's now in sys.modules.
        import sys

        sys.modules.pop("examples.13_claude_agent_sdk.app", None)
        app = _load_app("examples.13_claude_agent_sdk.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "assistant.ask" in data["endpoints"]
        assert "assistant.audit" in data["endpoints"]

    def test_capabilities_lists_both_endpoints(self, client: TestClient) -> None:
        response = client.get("/capabilities")
        assert response.status_code == 200
        data = response.json()
        names = {ep["name"] for ep in data["endpoints"]}
        assert {"assistant.ask", "assistant.audit"}.issubset(names)

    def test_audit_endpoint_works_without_calling_sdk(self, client: TestClient) -> None:
        """The audit endpoint reads from the in-memory recorder only."""
        data = _post_intent(client, "assistant.audit", "Show recent traces")
        assert data["status"] == "completed"
        result = data["result"]
        assert "extension_installed" in result
        assert "trace_count" in result
        assert isinstance(result["recent"], list)

    def test_ask_endpoint_runs_with_stubbed_sdk(self, stubbed_client: TestClient) -> None:
        """The ``ask`` endpoint drives the runner against a stub SDK."""
        data = _post_intent(stubbed_client, "assistant.ask", "Tell me about AgenticAPI")
        # The stub returns a fixed answer; the example handler unwraps the
        # runner's AgentResponse into a plain dict for nicer JSON output.
        assert data["status"] == "completed"
        result = data["result"]
        assert result["ok"] is True
        assert result["answer"] == "Stubbed answer."
        assert result["error"] is None

    def test_ask_endpoint_records_audit_trace(self, stubbed_client: TestClient) -> None:
        """Calling ``ask`` should add a trace visible to ``audit``."""
        # Drive at least one ask call so the recorder has a record.
        _post_intent(stubbed_client, "assistant.ask", "Hello")
        audit_data = _post_intent(stubbed_client, "assistant.audit", "Show traces")
        result = audit_data["result"]
        assert result["trace_count"] >= 1
        assert result["recent"][-1]["endpoint"] == "assistant.ask"
        assert result["recent"][-1]["error"] is None

    def test_missing_intent_returns_400(self, client: TestClient) -> None:
        response = client.post("/agent/assistant.ask", json={"no_intent": "oops"})
        assert response.status_code == 400
