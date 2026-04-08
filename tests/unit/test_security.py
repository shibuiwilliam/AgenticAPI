"""Tests for authentication and authorization security module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from agenticapi.app import AgenticApp
from agenticapi.exceptions import AuthenticationError
from agenticapi.routing import AgentRouter
from agenticapi.security import (
    APIKeyHeader,
    APIKeyQuery,
    AuthCredentials,
    Authenticator,
    AuthUser,
    HTTPBasic,
    HTTPBearer,
)

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    headers: dict[str, str] | None = None,
    query_string: str = "",
) -> Any:
    """Create a minimal mock request for testing security schemes."""
    from starlette.requests import Request

    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "query_string": query_string.encode(),
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    return Request(scope)


async def _valid_verify(creds: AuthCredentials) -> AuthUser | None:
    """A verify function that accepts 'valid-token'."""
    if creds.credentials == "valid-token":
        return AuthUser(user_id="user-1", username="alice", roles=("admin",))
    return None


async def _always_verify(creds: AuthCredentials) -> AuthUser | None:
    """A verify function that always succeeds."""
    return AuthUser(user_id="user-1", username="test")


# ---------------------------------------------------------------------------
# AuthCredentials
# ---------------------------------------------------------------------------


class TestAuthCredentials:
    def test_frozen(self) -> None:
        creds = AuthCredentials(scheme="bearer", credentials="token123")
        with pytest.raises(AttributeError):
            creds.scheme = "other"  # type: ignore[misc]

    def test_defaults(self) -> None:
        creds = AuthCredentials(scheme="apikey", credentials="key")
        assert creds.scopes == ()

    def test_with_scopes(self) -> None:
        creds = AuthCredentials(scheme="bearer", credentials="t", scopes=("read", "write"))
        assert creds.scopes == ("read", "write")

    def test_equality(self) -> None:
        a = AuthCredentials(scheme="bearer", credentials="t")
        b = AuthCredentials(scheme="bearer", credentials="t")
        assert a == b


# ---------------------------------------------------------------------------
# AuthUser
# ---------------------------------------------------------------------------


class TestAuthUser:
    def test_frozen(self) -> None:
        user = AuthUser(user_id="u1")
        with pytest.raises(AttributeError):
            user.user_id = "u2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        user = AuthUser(user_id="u1")
        assert user.username is None
        assert user.roles == ()
        assert user.scopes == ()
        assert user.metadata == {}

    def test_full_construction(self) -> None:
        user = AuthUser(
            user_id="u1",
            username="alice",
            roles=("admin", "operator"),
            scopes=("read", "write"),
            metadata={"org": "acme"},
        )
        assert user.user_id == "u1"
        assert user.username == "alice"
        assert user.roles == ("admin", "operator")
        assert user.metadata["org"] == "acme"


# ---------------------------------------------------------------------------
# APIKeyHeader
# ---------------------------------------------------------------------------


class TestAPIKeyHeader:
    async def test_extracts_key_from_header(self) -> None:
        scheme = APIKeyHeader(name="X-API-Key")
        request = _make_request(headers={"X-API-Key": "my-secret-key"})
        creds = await scheme(request)
        assert creds is not None
        assert creds.scheme == "apikey"
        assert creds.credentials == "my-secret-key"

    async def test_raises_when_missing_auto_error_true(self) -> None:
        scheme = APIKeyHeader(name="X-API-Key", auto_error=True)
        request = _make_request()
        with pytest.raises(AuthenticationError, match="X-API-Key"):
            await scheme(request)

    async def test_returns_none_when_missing_auto_error_false(self) -> None:
        scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
        request = _make_request()
        result = await scheme(request)
        assert result is None

    async def test_custom_header_name(self) -> None:
        scheme = APIKeyHeader(name="Authorization-Token")
        request = _make_request(headers={"Authorization-Token": "abc123"})
        creds = await scheme(request)
        assert creds is not None
        assert creds.credentials == "abc123"

    def test_scheme_name(self) -> None:
        scheme = APIKeyHeader()
        assert scheme.scheme_name == "apiKeyHeader"


# ---------------------------------------------------------------------------
# APIKeyQuery
# ---------------------------------------------------------------------------


class TestAPIKeyQuery:
    async def test_extracts_key_from_query(self) -> None:
        scheme = APIKeyQuery(name="api_key")
        request = _make_request(query_string="api_key=secret123")
        creds = await scheme(request)
        assert creds is not None
        assert creds.credentials == "secret123"

    async def test_raises_when_missing_auto_error_true(self) -> None:
        scheme = APIKeyQuery(name="api_key")
        request = _make_request()
        with pytest.raises(AuthenticationError, match="api_key"):
            await scheme(request)

    async def test_returns_none_when_missing_auto_error_false(self) -> None:
        scheme = APIKeyQuery(name="api_key", auto_error=False)
        request = _make_request()
        result = await scheme(request)
        assert result is None

    def test_scheme_name(self) -> None:
        scheme = APIKeyQuery()
        assert scheme.scheme_name == "apiKeyQuery"


# ---------------------------------------------------------------------------
# HTTPBearer
# ---------------------------------------------------------------------------


class TestHTTPBearer:
    async def test_extracts_bearer_token(self) -> None:
        scheme = HTTPBearer()
        request = _make_request(headers={"Authorization": "Bearer my-jwt-token"})
        creds = await scheme(request)
        assert creds is not None
        assert creds.scheme == "bearer"
        assert creds.credentials == "my-jwt-token"

    async def test_raises_when_missing_auto_error_true(self) -> None:
        scheme = HTTPBearer()
        request = _make_request()
        with pytest.raises(AuthenticationError, match="Authorization"):
            await scheme(request)

    async def test_returns_none_when_missing_auto_error_false(self) -> None:
        scheme = HTTPBearer(auto_error=False)
        request = _make_request()
        result = await scheme(request)
        assert result is None

    async def test_rejects_non_bearer_scheme(self) -> None:
        scheme = HTTPBearer()
        request = _make_request(headers={"Authorization": "Basic dXNlcjpwYXNz"})
        with pytest.raises(AuthenticationError, match="Bearer"):
            await scheme(request)

    async def test_non_bearer_returns_none_auto_error_false(self) -> None:
        scheme = HTTPBearer(auto_error=False)
        request = _make_request(headers={"Authorization": "Basic dXNlcjpwYXNz"})
        result = await scheme(request)
        assert result is None

    def test_scheme_name(self) -> None:
        scheme = HTTPBearer()
        assert scheme.scheme_name == "bearer"


# ---------------------------------------------------------------------------
# HTTPBasic
# ---------------------------------------------------------------------------


class TestHTTPBasic:
    async def test_extracts_basic_credentials(self) -> None:
        import base64

        encoded = base64.b64encode(b"alice:password123").decode()
        scheme = HTTPBasic()
        request = _make_request(headers={"Authorization": f"Basic {encoded}"})
        creds = await scheme(request)
        assert creds is not None
        assert creds.scheme == "basic"
        assert creds.credentials == "alice:password123"

    async def test_raises_when_missing_auto_error_true(self) -> None:
        scheme = HTTPBasic()
        request = _make_request()
        with pytest.raises(AuthenticationError, match="Authorization"):
            await scheme(request)

    async def test_returns_none_when_missing_auto_error_false(self) -> None:
        scheme = HTTPBasic(auto_error=False)
        request = _make_request()
        result = await scheme(request)
        assert result is None

    async def test_rejects_non_basic_scheme(self) -> None:
        scheme = HTTPBasic()
        request = _make_request(headers={"Authorization": "Bearer token"})
        with pytest.raises(AuthenticationError, match="Basic"):
            await scheme(request)

    async def test_rejects_invalid_base64(self) -> None:
        scheme = HTTPBasic()
        request = _make_request(headers={"Authorization": "Basic !!!invalid!!!"})
        with pytest.raises(AuthenticationError, match="encoding"):
            await scheme(request)

    async def test_invalid_base64_returns_none_auto_error_false(self) -> None:
        scheme = HTTPBasic(auto_error=False)
        request = _make_request(headers={"Authorization": "Basic !!!invalid!!!"})
        result = await scheme(request)
        assert result is None

    def test_scheme_name(self) -> None:
        scheme = HTTPBasic()
        assert scheme.scheme_name == "basic"


# ---------------------------------------------------------------------------
# Authenticator
# ---------------------------------------------------------------------------


class TestAuthenticator:
    def test_frozen(self) -> None:
        auth = Authenticator(scheme=APIKeyHeader(), verify=_valid_verify)
        with pytest.raises(AttributeError):
            auth.scheme = APIKeyHeader()  # type: ignore[misc]

    async def test_full_chain_success(self) -> None:
        scheme = APIKeyHeader(name="X-Key")
        auth = Authenticator(scheme=scheme, verify=_valid_verify)

        request = _make_request(headers={"X-Key": "valid-token"})
        creds = await auth.scheme(request)
        assert creds is not None
        user = await auth.verify(creds)
        assert user is not None
        assert user.user_id == "user-1"
        assert user.username == "alice"

    async def test_full_chain_invalid_credentials(self) -> None:
        scheme = APIKeyHeader(name="X-Key")
        auth = Authenticator(scheme=scheme, verify=_valid_verify)

        request = _make_request(headers={"X-Key": "wrong-token"})
        creds = await auth.scheme(request)
        assert creds is not None
        user = await auth.verify(creds)
        assert user is None


# ---------------------------------------------------------------------------
# enable_mcp + auth on endpoint
# ---------------------------------------------------------------------------


class TestEndpointAuthField:
    def test_endpoint_stores_auth(self) -> None:
        auth = Authenticator(scheme=APIKeyHeader(), verify=_valid_verify)
        app = AgenticApp()

        @app.agent_endpoint(name="test", auth=auth)
        async def test_agent(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {}

        assert app._endpoints["test"].auth is auth

    def test_endpoint_auth_defaults_none(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="test")
        async def test_agent(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {}

        assert app._endpoints["test"].auth is None

    def test_router_auth_propagates(self) -> None:
        auth = Authenticator(scheme=APIKeyHeader(), verify=_valid_verify)
        router = AgentRouter(prefix="api", auth=auth)

        @router.agent_endpoint(name="items")
        async def items_agent(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {}

        assert router.endpoints["api.items"].auth is auth

    def test_router_endpoint_auth_overrides_router_auth(self) -> None:
        router_auth = Authenticator(scheme=APIKeyHeader(), verify=_valid_verify)
        endpoint_auth = Authenticator(scheme=HTTPBearer(), verify=_always_verify)
        router = AgentRouter(prefix="api", auth=router_auth)

        @router.agent_endpoint(name="special", auth=endpoint_auth)
        async def special_agent(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {}

        assert router.endpoints["api.special"].auth is endpoint_auth

    def test_include_router_preserves_auth(self) -> None:
        auth = Authenticator(scheme=APIKeyHeader(), verify=_valid_verify)
        app = AgenticApp()
        router = AgentRouter(prefix="api")

        @router.agent_endpoint(name="items", auth=auth)
        async def items_agent(intent: Intent, context: AgentContext) -> dict[str, Any]:
            return {}

        app.include_router(router)
        assert app._endpoints["api.items"].auth is auth
