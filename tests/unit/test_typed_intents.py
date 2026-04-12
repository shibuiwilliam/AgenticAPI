"""Unit tests for D4 — typed Intent[T] generic + structured-output schemas.

Covers the Intent generic dataclass, the IntentParser schema-aware path,
the scanner extracting T from Intent[T] handler signatures, and the
end-to-end flow through ``app.process_intent``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from starlette.testclient import TestClient

from agenticapi import AgenticApp, Intent
from agenticapi.dependencies import scan_handler
from agenticapi.interface.intent import IntentAction, IntentParser
from agenticapi.runtime.llm import MockBackend

# ---------------------------------------------------------------------------
# Module-level Pydantic models (must be importable for $ref resolution)
# ---------------------------------------------------------------------------


class OrderFilters(BaseModel):
    status: Literal["open", "shipped", "cancelled"] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class TicketQuery(BaseModel):
    severity: Literal["low", "medium", "high"] = "medium"
    keyword: str = ""


# ---------------------------------------------------------------------------
# Intent dataclass
# ---------------------------------------------------------------------------


class TestIntentDataclass:
    def test_bare_intent_still_works(self) -> None:
        """The legacy bare ``Intent(...)`` constructor stays valid."""
        i = Intent(raw="hello", action=IntentAction.READ, domain="general")
        assert i.params is None
        assert i.parameters == {}

    def test_typed_intent_constructs(self) -> None:
        """``Intent[T]`` accepts a typed payload via ``params=``."""
        params = OrderFilters(status="shipped", limit=50)
        i: Intent[OrderFilters] = Intent(
            raw="show shipped",
            action=IntentAction.READ,
            domain="order",
            params=params,
        )
        assert i.params is params
        assert i.params.status == "shipped"

    def test_intent_subscript_origin(self) -> None:
        """``Intent[T].__origin__`` resolves back to ``Intent``."""
        assert Intent[OrderFilters].__origin__ is Intent
        assert Intent[OrderFilters].__args__ == (OrderFilters,)


# ---------------------------------------------------------------------------
# Scanner extracts T
# ---------------------------------------------------------------------------


class TestScannerExtractsTypedSchema:
    def test_typed_intent_handler(self) -> None:
        """The scanner picks up ``Intent[T]`` from the handler signature."""

        async def handler(intent: Intent[OrderFilters]) -> dict:
            del intent
            return {}

        plan = scan_handler(handler)
        assert plan.intent_payload_schema is OrderFilters

    def test_bare_intent_handler(self) -> None:
        """A bare ``intent: Intent`` handler has no payload schema."""

        async def handler(intent: Intent) -> dict:
            del intent
            return {}

        plan = scan_handler(handler)
        assert plan.intent_payload_schema is None

    def test_legacy_unannotated_handler(self) -> None:
        """An unannotated handler has no payload schema."""

        async def handler(intent, context):
            del intent, context
            return {}

        plan = scan_handler(handler)
        assert plan.intent_payload_schema is None


# ---------------------------------------------------------------------------
# IntentParser schema-aware path
# ---------------------------------------------------------------------------


class TestIntentParserWithSchema:
    async def test_keyword_only_schema_with_defaults(self) -> None:
        """Without an LLM, schemas with defaults still produce a typed payload."""
        parser = IntentParser(llm=None)
        intent = await parser.parse("show orders", schema=OrderFilters)
        assert intent.params is not None
        assert isinstance(intent.params, OrderFilters)
        assert intent.params.limit == 20

    async def test_llm_path_constrains_to_schema(self) -> None:
        """With a mock LLM, the parser asks for and receives a typed payload."""
        backend = MockBackend(
            structured_responses=[{"status": "shipped", "limit": 50}],
        )
        parser = IntentParser(llm=backend)
        intent = await parser.parse("show shipped", schema=OrderFilters)
        assert intent.params is not None
        assert intent.params.status == "shipped"
        assert intent.params.limit == 50
        # The parser should have forwarded the schema to the backend.
        prompt = backend.prompts[0]
        assert prompt.response_schema is not None
        assert prompt.response_schema_name == "OrderFilters"

    async def test_invalid_payload_falls_back(self) -> None:
        """Validation failure falls back to a defaults-only typed intent."""
        backend = MockBackend(
            structured_responses=[{"limit": "not-an-int"}],  # invalid
        )
        parser = IntentParser(llm=backend)
        intent = await parser.parse("show", schema=OrderFilters)
        # Fallback path: params populated from defaults, ambiguity logged.
        assert intent.params is not None
        assert intent.params.limit == 20  # default
        assert any("typed schema" in a for a in intent.ambiguities)


# ---------------------------------------------------------------------------
# End-to-end through AgenticApp
# ---------------------------------------------------------------------------


class TestTypedIntentEndToEnd:
    def test_handler_receives_typed_payload(self) -> None:
        """Handler with ``Intent[OrderFilters]`` receives validated params."""
        backend = MockBackend(
            structured_responses=[{"status": "shipped", "limit": 25}],
        )
        app = AgenticApp(title="d4-e2e", llm=backend)

        @app.agent_endpoint(name="orders.query", autonomy_level="manual")
        async def query(intent: Intent[OrderFilters]) -> dict:
            return {
                "status": intent.params.status if intent.params else None,
                "limit": intent.params.limit if intent.params else None,
            }

        client = TestClient(app)
        body = client.post("/agent/orders.query", json={"intent": "show shipped 25"}).json()
        assert body["status"] == "completed"
        assert body["result"]["status"] == "shipped"
        assert body["result"]["limit"] == 25

    def test_two_endpoints_get_distinct_schemas(self) -> None:
        """Different endpoints receive their own typed payloads."""
        backend = MockBackend(
            structured_responses=[
                {"status": "open", "limit": 5},  # for orders
                {"severity": "high", "keyword": "outage"},  # for tickets
            ],
        )
        app = AgenticApp(title="d4-multi", llm=backend)

        @app.agent_endpoint(name="orders.query", autonomy_level="manual")
        async def orders(intent: Intent[OrderFilters]) -> dict:
            assert intent.params is not None
            return {"orders_status": intent.params.status}

        @app.agent_endpoint(name="tickets.query", autonomy_level="manual")
        async def tickets(intent: Intent[TicketQuery]) -> dict:
            assert intent.params is not None
            return {"ticket_severity": intent.params.severity}

        client = TestClient(app)
        b1 = client.post("/agent/orders.query", json={"intent": "open orders top 5"}).json()
        b2 = client.post("/agent/tickets.query", json={"intent": "high severity outage"}).json()

        assert b1["result"]["orders_status"] == "open"
        assert b2["result"]["ticket_severity"] == "high"

    def test_legacy_handler_still_works_alongside_typed(self) -> None:
        """A legacy handler and a typed handler can coexist in one app."""
        backend = MockBackend(
            responses=['{"action": "read", "domain": "user", "parameters": {}}'],
            structured_responses=[{"limit": 10}],
        )
        app = AgenticApp(title="d4-mixed", llm=backend)

        @app.agent_endpoint(name="legacy", autonomy_level="manual")
        async def legacy(intent, context):
            return {"raw": intent.raw}

        @app.agent_endpoint(name="typed", autonomy_level="manual")
        async def typed(intent: Intent[OrderFilters]) -> dict:
            return {"limit": intent.params.limit if intent.params else None}

        client = TestClient(app)
        legacy_body = client.post("/agent/legacy", json={"intent": "hello"}).json()
        typed_body = client.post("/agent/typed", json={"intent": "show 10"}).json()

        assert legacy_body["result"]["raw"] == "hello"
        assert typed_body["result"]["limit"] == 10

    def test_handler_can_use_intent_dot_parameters_for_back_compat(self) -> None:
        """The legacy ``intent.parameters`` dict mirrors ``params.model_dump()``."""
        backend = MockBackend(structured_responses=[{"status": "open", "limit": 7}])
        app = AgenticApp(title="d4-mirror", llm=backend)

        @app.agent_endpoint(name="orders.query", autonomy_level="manual")
        async def query(intent: Intent[OrderFilters]) -> dict:
            return {"from_dict": intent.parameters}

        client = TestClient(app)
        body = client.post("/agent/orders.query", json={"intent": "x"}).json()
        assert body["result"]["from_dict"]["status"] == "open"
        assert body["result"]["from_dict"]["limit"] == 7


# ---------------------------------------------------------------------------
# MockBackend structured-response support
# ---------------------------------------------------------------------------


class TestMockBackendStructuredOutput:
    async def test_synthesises_when_no_explicit_response(self) -> None:
        """Without an explicit structured response, schema defaults are used."""
        from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

        backend = MockBackend()
        prompt = LLMPrompt(
            system="parse",
            messages=[LLMMessage(role="user", content="x")],
            response_schema=OrderFilters.model_json_schema(),
            response_schema_name="OrderFilters",
        )
        response = await backend.generate(prompt)
        # Synthesised payload should be JSON; defaults from the schema.
        assert response.content.startswith("{")

    async def test_returns_explicit_structured_response(self) -> None:
        from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

        backend = MockBackend(structured_responses=[{"status": "cancelled", "limit": 1}])
        prompt = LLMPrompt(
            system="x",
            messages=[LLMMessage(role="user", content="x")],
            response_schema=OrderFilters.model_json_schema(),
            response_schema_name="OrderFilters",
        )
        response = await backend.generate(prompt)
        assert "cancelled" in response.content
        assert "1" in response.content
