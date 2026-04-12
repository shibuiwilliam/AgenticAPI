"""Unit tests for ``agenticapi.observability.propagation`` (Phase A5).

Tests run in the no-OTEL environment so they verify the **degraded
no-op semantics**: extraction returns ``None``, injection leaves the
dict untouched, and the request handler still works when an incoming
``traceparent`` header is present.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from agenticapi import AgenticApp
from agenticapi.app import _headers_from_scope
from agenticapi.observability import (
    extract_context_from_headers,
    headers_with_traceparent,
    inject_context_into_headers,
    is_propagation_available,
)


class TestNoopPropagation:
    def test_otel_not_installed_in_test_env(self) -> None:
        assert is_propagation_available() is False

    def test_extract_returns_none_without_otel(self) -> None:
        ctx = extract_context_from_headers({"traceparent": "00-abc-def-01"})
        assert ctx is None

    def test_extract_returns_none_for_empty_headers(self) -> None:
        assert extract_context_from_headers(None) is None
        assert extract_context_from_headers({}) is None

    def test_inject_is_no_op_without_otel(self) -> None:
        out = inject_context_into_headers({"x-existing": "foo"})
        assert out == {"x-existing": "foo"}

    def test_headers_with_traceparent_returns_copy(self) -> None:
        base = {"x-base": "bar"}
        out = headers_with_traceparent(base)
        assert out == {"x-base": "bar"}
        # Mutating the result must not affect the input.
        out["x-other"] = "baz"
        assert "x-other" not in base


class TestHeadersFromScope:
    def test_returns_none_for_missing_scope(self) -> None:
        assert _headers_from_scope(None) is None
        assert _headers_from_scope({}) is None

    def test_decodes_bytes_headers(self) -> None:
        scope = {"headers": [(b"Traceparent", b"00-abc-def-01")]}
        out = _headers_from_scope(scope)
        assert out == {"traceparent": "00-abc-def-01"}

    def test_lowercases_header_names(self) -> None:
        scope = {"headers": [(b"X-Custom-Header", b"value")]}
        out = _headers_from_scope(scope)
        assert out == {"x-custom-header": "value"}

    def test_handles_string_headers(self) -> None:
        scope = {"headers": [("X-Foo", "bar")]}
        out = _headers_from_scope(scope)
        assert out == {"x-foo": "bar"}

    def test_skips_malformed_entries(self) -> None:
        scope = {"headers": [(b"x-good", b"y"), "malformed", (b"only-one",)]}
        out = _headers_from_scope(scope)
        assert out == {"x-good": "y"}


class TestRequestHandlerHonoursTraceparent:
    def test_request_with_traceparent_succeeds(self) -> None:
        """Even without OTEL installed, an incoming traceparent must not break the request."""
        app = AgenticApp(title="a5-test")

        @app.agent_endpoint(name="ep", autonomy_level="auto")
        async def handler(intent, context):
            return {"ok": True}

        client = TestClient(app)
        response = client.post(
            "/agent/ep",
            json={"intent": "x"},
            headers={"traceparent": "00-deadbeef000000000000000000000001-0102030405060708-01"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
