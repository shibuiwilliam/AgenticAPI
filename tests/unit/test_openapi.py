"""Tests for OpenAPI schema generation and docs routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from agenticapi.app import AgenticApp
from agenticapi.interface.intent import IntentScope

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
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
