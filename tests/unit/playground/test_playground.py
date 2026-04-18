"""Tests for the playground backend API and mounting."""

from __future__ import annotations

from typing import Any

from starlette.testclient import TestClient

from agenticapi import AgenticApp


def _make_app(playground_url: str | None = "/_playground") -> AgenticApp:
    """Create a simple app with the playground enabled."""
    app = AgenticApp(
        title="Test App",
        playground_url=playground_url,
    )

    @app.agent_endpoint(name="hello", description="A test endpoint")
    async def hello(intent: Any, context: Any) -> dict[str, str]:
        return {"message": "Hello!"}

    @app.agent_endpoint(name="echo", description="Echoes the intent")
    async def echo(intent: Any, context: Any) -> dict[str, str]:
        return {"echo": str(intent.raw)}

    return app


class TestPlaygroundMounting:
    """Test that the playground mounts correctly."""

    def test_playground_serves_html(self) -> None:
        app = _make_app("/_playground")
        client = TestClient(app)
        r = client.get("/_playground")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "AgenticAPI Playground" in r.text

    def test_playground_disabled_returns_404(self) -> None:
        app = _make_app(playground_url=None)
        client = TestClient(app)
        r = client.get("/_playground")
        assert r.status_code in (404, 405)

    def test_custom_playground_url(self) -> None:
        app = _make_app("/_debug")
        client = TestClient(app)
        r = client.get("/_debug")
        assert r.status_code == 200
        assert "AgenticAPI Playground" in r.text


class TestPlaygroundEndpointsAPI:
    """Test GET /_playground/api/endpoints."""

    def test_lists_endpoints(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_playground/api/endpoints")
        assert r.status_code == 200
        endpoints = r.json()
        assert isinstance(endpoints, list)
        names = [e["name"] for e in endpoints]
        assert "hello" in names
        assert "echo" in names

    def test_endpoint_metadata(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_playground/api/endpoints")
        endpoints = r.json()
        hello = next(e for e in endpoints if e["name"] == "hello")
        assert hello["path"] == "/agent/hello"
        assert hello["description"] == "A test endpoint"
        assert hello["auth_required"] is False


class TestPlaygroundTracesAPI:
    """Test GET /_playground/api/traces."""

    def test_traces_empty_without_harness(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/_playground/api/traces")
        assert r.status_code == 200
        assert r.json() == []


class TestPlaygroundChatAPI:
    """Test POST /_playground/api/chat."""

    def test_chat_proxies_to_endpoint(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.post(
            "/_playground/api/chat",
            json={"endpoint": "hello", "message": "hi there"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["result"]["message"] == "Hello!"

    def test_chat_unknown_endpoint(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.post(
            "/_playground/api/chat",
            json={"endpoint": "nonexistent", "message": "hi"},
        )
        assert r.status_code == 404


class TestHealthStillWorks:
    """Ensure playground doesn't break existing routes."""

    def test_health_with_playground(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.get("/health")
        assert r.status_code == 200

    def test_agent_endpoint_with_playground(self) -> None:
        app = _make_app()
        client = TestClient(app)
        r = client.post("/agent/hello", json={"intent": "test"})
        assert r.status_code == 200
