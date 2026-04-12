"""Tests for OpenAPI schema generation and docs routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from starlette.testclient import TestClient

# ``Intent`` must be importable at runtime (not just TYPE_CHECKING)
# because the handler signatures below annotate parameters as
# ``Intent[OrderFilters]`` and the framework's scanner resolves those
# string annotations via ``typing.get_type_hints``, which walks the
# handler's module globals.
from agenticapi import Intent  # noqa: TC001
from agenticapi.app import AgenticApp
from agenticapi.interface.intent import IntentScope

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext


def _build_app(**kwargs: object) -> AgenticApp:
    app = AgenticApp(title="Test API", version="2.0.0", description="Test description", **kwargs)  # type: ignore[arg-type]

    @app.agent_endpoint(
        name="orders.query",
        description="Query orders",
        intent_scope=IntentScope(allowed_intents=["order.*"], denied_intents=["order.bulk_delete"]),
        autonomy_level="auto",
    )
    async def orders_query(intent: Intent, context: AgentContext) -> dict[str, str]:
        return {"ok": "true"}

    @app.agent_endpoint(name="greeter", description="Simple greeter")
    async def greeter(intent: Intent, context: AgentContext) -> dict[str, str]:
        return {"hello": "world"}

    return app


class TestOpenAPISchema:
    def test_openapi_json_served(self) -> None:
        client = TestClient(_build_app())
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["openapi"] == "3.1.0"
        assert schema["info"]["title"] == "Test API"
        assert schema["info"]["version"] == "2.0.0"
        assert schema["info"]["description"] == "Test description"

    def test_schema_contains_agent_endpoints(self) -> None:
        client = TestClient(_build_app())
        schema = client.get("/openapi.json").json()
        assert "/agent/orders.query" in schema["paths"]
        assert "/agent/greeter" in schema["paths"]
        assert "post" in schema["paths"]["/agent/orders.query"]
        assert "post" in schema["paths"]["/agent/greeter"]

    def test_schema_contains_health(self) -> None:
        client = TestClient(_build_app())
        schema = client.get("/openapi.json").json()
        assert "/health" in schema["paths"]
        assert "get" in schema["paths"]["/health"]

    def test_endpoint_metadata_in_schema(self) -> None:
        client = TestClient(_build_app())
        schema = client.get("/openapi.json").json()
        op = schema["paths"]["/agent/orders.query"]["post"]
        assert op["summary"] == "Query orders"
        assert "auto" in op.get("description", "")
        assert "order.*" in op.get("description", "")
        assert "order.bulk_delete" in op.get("description", "")

    def test_tags_from_dotted_name(self) -> None:
        client = TestClient(_build_app())
        schema = client.get("/openapi.json").json()
        orders_op = schema["paths"]["/agent/orders.query"]["post"]
        greeter_op = schema["paths"]["/agent/greeter"]["post"]
        assert "orders" in orders_op["tags"]
        assert "default" in greeter_op["tags"]

    def test_request_body_schema(self) -> None:
        client = TestClient(_build_app())
        schema = client.get("/openapi.json").json()
        op = schema["paths"]["/agent/orders.query"]["post"]
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        assert "intent" in body_schema["properties"]
        assert "session_id" in body_schema["properties"]

    def test_response_schema(self) -> None:
        client = TestClient(_build_app())
        schema = client.get("/openapi.json").json()
        op = schema["paths"]["/agent/orders.query"]["post"]
        resp_schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert "result" in resp_schema["properties"]
        assert "status" in resp_schema["properties"]
        assert "confidence" in resp_schema["properties"]


class TestSwaggerUI:
    def test_docs_served(self) -> None:
        client = TestClient(_build_app())
        response = client.get("/docs")
        assert response.status_code == 200
        assert "swagger-ui" in response.text.lower()
        assert "openapi.json" in response.text

    def test_redoc_served(self) -> None:
        client = TestClient(_build_app())
        response = client.get("/redoc")
        assert response.status_code == 200
        assert "redoc" in response.text.lower()
        assert "openapi.json" in response.text


class TestDocsDisabled:
    def test_no_docs_when_openapi_url_none(self) -> None:
        client = TestClient(_build_app(openapi_url=None))
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404

    def test_agent_endpoints_still_work(self) -> None:
        client = TestClient(_build_app(openapi_url=None))
        response = client.post("/agent/greeter", json={"intent": "hello"})
        assert response.status_code == 200


class TestCustomUrls:
    def test_custom_openapi_url(self) -> None:
        client = TestClient(_build_app(openapi_url="/api/schema.json", docs_url="/api/docs", redoc_url="/api/redoc"))
        assert client.get("/api/schema.json").status_code == 200
        assert client.get("/api/docs").status_code == 200
        assert client.get("/api/redoc").status_code == 200
        # Default paths should not exist
        assert client.get("/openapi.json").status_code == 404


# ---------------------------------------------------------------------------
# Phase D7 — Typed Intent[T] request-body schema in OpenAPI
# ---------------------------------------------------------------------------


class OrderFilters(BaseModel):
    """Module-level model so ``$ref`` resolution has a stable name."""

    status: Literal["open", "shipped", "cancelled"] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class TicketFilters(BaseModel):
    severity: Literal["low", "medium", "high"] = "medium"
    keyword: str = ""


def _build_typed_app() -> AgenticApp:
    """Build an app with one typed and one untyped endpoint for D7 tests."""
    app = AgenticApp(title="Typed API", version="1.0.0")

    @app.agent_endpoint(name="orders.query", description="Typed order query")
    async def orders_query(intent: Intent[OrderFilters]) -> dict[str, str]:
        del intent
        return {"ok": "true"}

    @app.agent_endpoint(name="tickets.search", description="Typed ticket search")
    async def tickets_search(intent: Intent[TicketFilters]) -> dict[str, str]:
        del intent
        return {"ok": "true"}

    @app.agent_endpoint(name="greeter", description="Legacy untyped endpoint")
    async def greeter(intent: Intent, context: AgentContext) -> dict[str, str]:
        del intent, context
        return {"hello": "world"}

    return app


class TestTypedRequestBodySchema:
    """Phase D7: ``Intent[T]`` handlers emit per-endpoint request bodies."""

    def test_typed_endpoint_references_payload_schema(self) -> None:
        """A handler declared as ``Intent[OrderFilters]`` emits a ``$ref``
        to ``OrderFilters`` in its request body schema."""
        client = TestClient(_build_typed_app())
        schema = client.get("/openapi.json").json()

        op = schema["paths"]["/agent/orders.query"]["post"]
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]

        # ``intent`` stays as a plain string — raw NL fallback always works.
        assert "intent" in body_schema["properties"]
        # ``parameters`` now $ref's the typed payload model.
        params_prop = body_schema["properties"]["parameters"]
        assert params_prop["$ref"] == "#/components/schemas/OrderFilters"

    def test_typed_endpoint_registers_component_schema(self) -> None:
        """The payload model is registered under ``components/schemas``."""
        client = TestClient(_build_typed_app())
        schema = client.get("/openapi.json").json()

        assert "components" in schema
        assert "OrderFilters" in schema["components"]["schemas"]
        order_schema = schema["components"]["schemas"]["OrderFilters"]
        assert order_schema["type"] == "object"
        # The Pydantic-derived schema carries the ``limit`` constraint.
        assert "limit" in order_schema["properties"]
        assert order_schema["properties"]["limit"].get("maximum") == 100

    def test_multiple_typed_endpoints_register_distinct_schemas(self) -> None:
        """Two typed endpoints with different payload models produce
        two distinct entries under ``components/schemas``."""
        client = TestClient(_build_typed_app())
        schema = client.get("/openapi.json").json()

        components = schema["components"]["schemas"]
        assert "OrderFilters" in components
        assert "TicketFilters" in components

        tickets_body = schema["paths"]["/agent/tickets.search"]["post"]["requestBody"]
        tickets_schema = tickets_body["content"]["application/json"]["schema"]
        assert tickets_schema["properties"]["parameters"]["$ref"] == "#/components/schemas/TicketFilters"

    def test_untyped_endpoint_keeps_generic_request_shape(self) -> None:
        """A legacy ``Intent``-annotated handler still gets the generic
        ``{"intent": string, ...}`` body — backward compatible."""
        client = TestClient(_build_typed_app())
        schema = client.get("/openapi.json").json()

        op = schema["paths"]["/agent/greeter"]["post"]
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]

        assert "intent" in body_schema["properties"]
        # No ``parameters`` $ref because no Intent[T] annotation.
        assert "parameters" not in body_schema["properties"]

    def test_typed_endpoint_still_has_intent_string_fallback(self) -> None:
        """Typed endpoints accept either a raw ``intent`` string (parsed
        via the LLM) or a structured ``parameters`` object — both shapes
        are advertised in the request body schema."""
        client = TestClient(_build_typed_app())
        schema = client.get("/openapi.json").json()

        body = schema["paths"]["/agent/orders.query"]["post"]["requestBody"]
        body_schema = body["content"]["application/json"]["schema"]
        intent_prop = body_schema["properties"]["intent"]
        # The ``intent`` property is still the generic string shape.
        assert intent_prop["type"] == "string"
