"""Tests for custom response types: HTMLResult, PlainTextResult."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from httpx import ASGITransport, AsyncClient

from agenticapi.app import AgenticApp
from agenticapi.interface.response import HTMLResult, PlainTextResult

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


class TestHTMLResult:
    def test_to_response_returns_html(self) -> None:
        result = HTMLResult(content="<h1>Hello</h1>")
        response = result.to_response()
        assert response.body == b"<h1>Hello</h1>"
        assert "text/html" in response.media_type

    def test_to_response_with_bytes(self) -> None:
        result = HTMLResult(content=b"<p>Bytes</p>")
        response = result.to_response()
        assert b"<p>Bytes</p>" in response.body

    def test_custom_status_code(self) -> None:
        result = HTMLResult(content="<h1>Not Found</h1>", status_code=404)
        response = result.to_response()
        assert response.status_code == 404

    def test_custom_headers(self) -> None:
        result = HTMLResult(content="<p>Hi</p>", headers={"X-Custom": "value"})
        response = result.to_response()
        assert response.headers["x-custom"] == "value"


class TestPlainTextResult:
    def test_to_response_returns_text(self) -> None:
        result = PlainTextResult(content="Hello, world!")
        response = result.to_response()
        assert response.body == b"Hello, world!"
        assert "text/plain" in response.media_type

    def test_custom_status_code(self) -> None:
        result = PlainTextResult(content="OK", status_code=201)
        response = result.to_response()
        assert response.status_code == 201


class TestHTMLResultInHandler:
    async def test_handler_returns_html(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="page")
        async def page(intent: Intent, context: AgentContext) -> HTMLResult:
            return HTMLResult(content=f"<h1>You said: {intent.raw}</h1>")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/page", json={"intent": "hello"})

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<h1>You said: hello</h1>" in response.text

    async def test_handler_returns_plain_text(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="status")
        async def status(intent: Intent, context: AgentContext) -> PlainTextResult:
            return PlainTextResult(content="OK")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/status", json={"intent": "check"})

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert response.text == "OK"

    async def test_html_bypasses_json_wrapping(self) -> None:
        """HTMLResult should NOT be wrapped in AgentResponse JSON."""
        app = AgenticApp()

        @app.agent_endpoint(name="html")
        async def html_page(intent: Intent, context: AgentContext) -> HTMLResult:
            return HTMLResult(content="<p>Raw HTML</p>")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/html", json={"intent": "test"})

        # Should be raw HTML, not JSON-wrapped
        assert response.text == "<p>Raw HTML</p>"
        assert "application/json" not in response.headers["content-type"]

    async def test_starlette_html_response_also_works(self) -> None:
        """Direct Starlette HTMLResponse should also pass through."""
        from starlette.responses import HTMLResponse

        app = AgenticApp()

        @app.agent_endpoint(name="raw")
        async def raw_html(intent: Intent, context: AgentContext) -> Any:
            return HTMLResponse(content="<b>Direct</b>")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/raw", json={"intent": "test"})

        assert response.text == "<b>Direct</b>"
        assert "text/html" in response.headers["content-type"]
