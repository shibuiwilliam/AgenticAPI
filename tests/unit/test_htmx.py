"""Tests for HTMX support: HtmxHeaders and htmx_response_headers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from httpx import ASGITransport, AsyncClient

from agenticapi.app import AgenticApp
from agenticapi.interface.htmx import HtmxHeaders, htmx_response_headers
from agenticapi.interface.response import HTMLResult

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


class TestHtmxHeaders:
    def test_from_scope_with_htmx_request(self) -> None:
        scope: dict[str, Any] = {
            "headers": [
                (b"hx-request", b"true"),
                (b"hx-target", b"content"),
                (b"hx-trigger", b"btn"),
            ]
        }
        h = HtmxHeaders.from_scope(scope)
        assert h.is_htmx is True
        assert h.target == "content"
        assert h.trigger == "btn"

    def test_from_scope_without_htmx(self) -> None:
        scope: dict[str, Any] = {"headers": [(b"content-type", b"application/json")]}
        h = HtmxHeaders.from_scope(scope)
        assert h.is_htmx is False
        assert h.target is None

    def test_from_scope_all_headers(self) -> None:
        scope: dict[str, Any] = {
            "headers": [
                (b"hx-request", b"true"),
                (b"hx-boosted", b"true"),
                (b"hx-target", b"main"),
                (b"hx-trigger", b"link"),
                (b"hx-trigger-name", b"nav"),
                (b"hx-current-url", b"http://example.com/page"),
                (b"hx-prompt", b"Enter name"),
            ]
        }
        h = HtmxHeaders.from_scope(scope)
        assert h.is_htmx is True
        assert h.boosted is True
        assert h.target == "main"
        assert h.trigger == "link"
        assert h.trigger_name == "nav"
        assert h.current_url == "http://example.com/page"
        assert h.prompt == "Enter name"

    def test_from_empty_scope(self) -> None:
        h = HtmxHeaders.from_scope({})
        assert h.is_htmx is False


class TestHtmxResponseHeaders:
    def test_trigger(self) -> None:
        headers = htmx_response_headers(trigger="itemAdded")
        assert headers["HX-Trigger"] == "itemAdded"

    def test_redirect(self) -> None:
        headers = htmx_response_headers(redirect="/new-page")
        assert headers["HX-Redirect"] == "/new-page"

    def test_retarget_and_reswap(self) -> None:
        headers = htmx_response_headers(retarget="#sidebar", reswap="outerHTML")
        assert headers["HX-Retarget"] == "#sidebar"
        assert headers["HX-Reswap"] == "outerHTML"

    def test_refresh(self) -> None:
        headers = htmx_response_headers(refresh=True)
        assert headers["HX-Refresh"] == "true"

    def test_push_url_string(self) -> None:
        headers = htmx_response_headers(push_url="/items/1")
        assert headers["HX-Push-Url"] == "/items/1"

    def test_push_url_bool(self) -> None:
        headers = htmx_response_headers(push_url=False)
        assert headers["HX-Push-Url"] == "false"

    def test_empty_returns_empty_dict(self) -> None:
        headers = htmx_response_headers()
        assert headers == {}

    def test_combined_headers(self) -> None:
        headers = htmx_response_headers(
            trigger="refresh",
            trigger_after_settle="loaded",
            trigger_after_swap="swapped",
        )
        assert headers["HX-Trigger"] == "refresh"
        assert headers["HX-Trigger-After-Settle"] == "loaded"
        assert headers["HX-Trigger-After-Swap"] == "swapped"


class TestHtmxInHandler:
    async def test_htmx_request_returns_fragment(self) -> None:
        """Handler returns HTML fragment when HX-Request is present."""
        app = AgenticApp()

        @app.agent_endpoint(name="items")
        async def items(intent: Intent, context: AgentContext, htmx: HtmxHeaders) -> Any:
            if htmx.is_htmx:
                return HTMLResult(content="<li>Item 1</li><li>Item 2</li>")
            return HTMLResult(content="<html><body><ul id='list'></ul></body></html>")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # HTMX request
            response = await client.post(
                "/agent/items",
                json={"intent": "show items"},
                headers={"HX-Request": "true"},
            )
        assert response.status_code == 200
        assert "<li>Item 1</li>" in response.text
        assert "<html>" not in response.text

    async def test_non_htmx_request_returns_full_page(self) -> None:
        """Handler returns full page when HX-Request is absent."""
        app = AgenticApp()

        @app.agent_endpoint(name="items")
        async def items(intent: Intent, context: AgentContext, htmx: HtmxHeaders) -> Any:
            if htmx.is_htmx:
                return HTMLResult(content="<li>Fragment</li>")
            return HTMLResult(content="<html><body>Full page</body></html>")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/items", json={"intent": "show items"})
        assert "<html>" in response.text
        assert "Full page" in response.text

    async def test_htmx_response_headers_on_result(self) -> None:
        """HTMX response headers are included in the response."""
        app = AgenticApp()

        @app.agent_endpoint(name="add")
        async def add_item(intent: Intent, context: AgentContext, htmx: HtmxHeaders) -> HTMLResult:
            headers = htmx_response_headers(trigger="itemAdded", reswap="beforeend")
            return HTMLResult(content="<li>New item</li>", headers=headers)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agent/add",
                json={"intent": "add item"},
                headers={"HX-Request": "true"},
            )
        assert response.status_code == 200
        assert response.headers["hx-trigger"] == "itemAdded"
        assert response.headers["hx-reswap"] == "beforeend"

    async def test_handler_without_htmx_still_works(self) -> None:
        """Handlers without HtmxHeaders parameter work normally."""
        app = AgenticApp()

        @app.agent_endpoint(name="simple")
        async def simple(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"status": "ok"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/simple", json={"intent": "test"})
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"] == "ok"
