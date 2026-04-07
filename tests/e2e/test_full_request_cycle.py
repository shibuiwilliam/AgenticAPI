"""End-to-end test: full request cycle through all layers.

Tests the complete pipeline from raw request through intent parsing,
code generation, harness evaluation, sandbox execution, and response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from agenticapi.app import AgenticApp
from agenticapi.exceptions import ApprovalRequired, PolicyViolation
from agenticapi.harness.approval.rules import ApprovalRule
from agenticapi.harness.approval.workflow import ApprovalWorkflow
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.runtime.llm.mock import MockBackend

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


class TestFullRequestCycleHandlerBased:
    """E2E tests using direct handler invocation (no LLM)."""

    async def test_full_cycle_handler_success(self) -> None:
        """Request → intent parse → handler → response."""
        app = AgenticApp(title="E2E Test")

        @app.agent_endpoint(name="orders")
        async def orders_handler(intent: Intent, context: AgentContext) -> dict[str, object]:
            return {"order_count": 42, "action": intent.action.value}

        response = await app.process_intent("show orders", endpoint_name="orders")
        assert response.status == "completed"
        assert response.result["order_count"] == 42
        assert response.result["action"] == "read"

    async def test_full_cycle_with_session(self) -> None:
        """Multi-turn conversation with session continuity."""
        app = AgenticApp(title="E2E Test")

        @app.agent_endpoint(name="chat")
        async def chat_handler(intent: Intent, context: AgentContext) -> dict[str, object]:
            return {"session": context.session_id, "turn": intent.raw}

        response1 = await app.process_intent(
            "first turn",
            endpoint_name="chat",
            session_id="sess_1",
        )
        response2 = await app.process_intent(
            "second turn",
            endpoint_name="chat",
            session_id="sess_1",
        )

        assert response1.status == "completed"
        assert response2.status == "completed"

    async def test_full_cycle_intent_scope_violation(self) -> None:
        """Request denied by intent scope raises PolicyViolation."""
        from agenticapi.interface.intent import IntentScope

        app = AgenticApp(title="E2E Test")

        @app.agent_endpoint(
            name="read_only",
            intent_scope=IntentScope(
                allowed_intents=["*.read"],
                denied_intents=["*.write"],
            ),
        )
        async def handler(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"ok": "true"}

        with pytest.raises(PolicyViolation, match="intent_scope"):
            await app.process_intent("delete all orders", endpoint_name="read_only")


class TestFullRequestCycleWithHarness:
    """E2E tests using LLM + harness pipeline."""

    async def test_safe_code_full_pipeline(self) -> None:
        """Mock LLM → code gen → policy check → sandbox → audit → response."""
        # Response 1: intent parsing, Response 2: code generation
        mock_llm = MockBackend(
            responses=[
                '{"action": "read", "domain": "general", "parameters": {}, "confidence": 0.9, "ambiguities": []}',
                "result = 42",
            ]
        )
        engine = HarnessEngine(
            policies=[CodePolicy(denied_modules=["os", "subprocess"])],
        )
        app = AgenticApp(title="E2E Harness", harness=engine, llm=mock_llm)  # type: ignore[arg-type]

        @app.agent_endpoint(name="compute")
        async def handler(intent: Intent, context: AgentContext) -> None:
            pass  # Not used when LLM+harness is active

        response = await app.process_intent("compute something", endpoint_name="compute")

        assert response.status == "completed"
        assert response.result == 42
        assert response.generated_code == "result = 42"
        assert response.execution_trace_id is not None

        # Verify audit trail
        records = engine.audit_recorder.get_records()
        assert len(records) == 1
        assert records[0].generated_code == "result = 42"

    async def test_dangerous_code_blocked_full_pipeline(self) -> None:
        """Mock LLM returns dangerous code → policy blocks it."""
        mock_llm = MockBackend(
            responses=[
                '{"action": "read", "domain": "general", "parameters": {}, "confidence": 0.9, "ambiguities": []}',
                "import os\nos.system('rm -rf /')",
            ]
        )
        engine = HarnessEngine(
            policies=[CodePolicy(denied_modules=["os"])],
        )
        app = AgenticApp(title="E2E Blocked", harness=engine, llm=mock_llm)  # type: ignore[arg-type]

        @app.agent_endpoint(name="danger")
        async def handler(intent: Intent, context: AgentContext) -> None:
            pass

        with pytest.raises(PolicyViolation, match="os"):
            await app.process_intent("do something", endpoint_name="danger")

    async def test_approval_required_full_pipeline(self) -> None:
        """Write intent with approval workflow → ApprovalRequired."""
        mock_llm = MockBackend(
            responses=[
                '{"action": "write", "domain": "order", "parameters": {}, "confidence": 0.9, "ambiguities": []}',
                "result = 'deleted'",
            ]
        )
        approval = ApprovalWorkflow(
            rules=[ApprovalRule(name="write_gate", require_for_actions=["write"], approvers=["admin"])]
        )
        engine = HarnessEngine(
            policies=[],
            approval_workflow=approval,
        )
        app = AgenticApp(title="E2E Approval", harness=engine, llm=mock_llm)  # type: ignore[arg-type]

        @app.agent_endpoint(name="orders")
        async def handler(intent: Intent, context: AgentContext) -> None:
            pass

        with pytest.raises(ApprovalRequired) as exc_info:
            await app.process_intent("delete all cancelled orders", endpoint_name="orders")

        assert exc_info.value.request_id is not None
        assert exc_info.value.approvers == ["admin"]


class TestFullRequestCycleHTTP:
    """E2E tests via HTTP using Starlette TestClient."""

    def test_http_full_cycle(self) -> None:
        """HTTP POST → full pipeline → JSON response."""
        app = AgenticApp(title="E2E HTTP")

        @app.agent_endpoint(name="test")
        async def handler(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"message": f"Got: {intent.raw}"}

        client = TestClient(app)
        response = client.post("/agent/test", json={"intent": "hello world"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "hello world" in str(data["result"])

    def test_http_health_check(self) -> None:
        """GET /health returns app info."""
        app = AgenticApp(title="E2E", version="1.0.0")
        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"

    def test_http_unknown_endpoint_returns_400(self) -> None:
        """POST to unknown endpoint returns error."""
        app = AgenticApp(title="E2E")

        @app.agent_endpoint(name="exists")
        async def handler(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {}

        client = TestClient(app)
        response = client.post("/agent/nonexistent", json={"intent": "test"})
        assert response.status_code == 404

    def test_http_missing_intent_returns_400(self) -> None:
        """POST without intent field returns 400."""
        app = AgenticApp(title="E2E")

        @app.agent_endpoint(name="test")
        async def handler(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {}

        client = TestClient(app)
        response = client.post("/agent/test", json={"no_intent": "here"})
        assert response.status_code == 400
