"""Integration tests for authentication flow through full HTTP request cycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.testclient import TestClient

from agenticapi.app import AgenticApp
from agenticapi.security import (
    APIKeyHeader,
    AuthCredentials,
    Authenticator,
    AuthUser,
    HTTPBearer,
)

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_API_KEY = "secret-key-123"
VALID_BEARER = "valid-jwt-token"


async def _verify_api_key(creds: AuthCredentials) -> AuthUser | None:
    if creds.credentials == VALID_API_KEY:
        return AuthUser(user_id="user-1", username="alice", roles=("admin",))
    return None


async def _verify_bearer(creds: AuthCredentials) -> AuthUser | None:
    if creds.credentials == VALID_BEARER:
        return AuthUser(user_id="user-2", username="bob")
    return None


_api_key_auth = Authenticator(scheme=APIKeyHeader(name="X-API-Key"), verify=_verify_api_key)
_bearer_auth = Authenticator(scheme=HTTPBearer(), verify=_verify_bearer)


# ---------------------------------------------------------------------------
# Backward compatibility: no auth
# ---------------------------------------------------------------------------


class TestNoAuth:
    """Endpoints without auth work exactly as before."""

    def test_no_auth_endpoint_works_without_credentials(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="public")
        async def public_agent(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"message": "hello"}

        client = TestClient(app)
        response = client.post("/agent/public", json={"intent": "hello"})
        assert response.status_code == 200
        assert response.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# Per-endpoint auth
# ---------------------------------------------------------------------------


class TestEndpointAuth:
    """Auth configured on individual endpoints."""

    def test_returns_401_without_credentials(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="protected", auth=_api_key_auth)
        async def protected_agent(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"message": "secret"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/agent/protected", json={"intent": "hello"})
        assert response.status_code == 401

    def test_returns_401_with_invalid_credentials(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="protected", auth=_api_key_auth)
        async def protected_agent(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"message": "secret"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/agent/protected",
            json={"intent": "hello"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401

    def test_returns_200_with_valid_credentials(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="protected", auth=_api_key_auth)
        async def protected_agent(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"message": "secret data"}

        client = TestClient(app)
        response = client.post(
            "/agent/protected",
            json={"intent": "show data"},
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    def test_bearer_auth_works(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="api", auth=_bearer_auth)
        async def api_agent(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"ok": "true"}

        client = TestClient(app)
        response = client.post(
            "/agent/api",
            json={"intent": "hello"},
            headers={"Authorization": f"Bearer {VALID_BEARER}"},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# App-level auth
# ---------------------------------------------------------------------------


class TestAppLevelAuth:
    """Auth configured at the app level applies to all endpoints."""

    def test_app_auth_applies_to_all_endpoints(self) -> None:
        app = AgenticApp(auth=_api_key_auth)

        @app.agent_endpoint(name="orders")
        async def orders_agent(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"orders": "data"}

        @app.agent_endpoint(name="products")
        async def products_agent(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"products": "data"}

        client = TestClient(app, raise_server_exceptions=False)

        # Both endpoints should require auth
        assert client.post("/agent/orders", json={"intent": "hi"}).status_code == 401
        assert client.post("/agent/products", json={"intent": "hi"}).status_code == 401

        # Both work with valid key
        headers = {"X-API-Key": VALID_API_KEY}
        assert client.post("/agent/orders", json={"intent": "hi"}, headers=headers).status_code == 200
        assert client.post("/agent/products", json={"intent": "hi"}, headers=headers).status_code == 200

    def test_endpoint_auth_overrides_app_auth(self) -> None:
        """Endpoint-level auth takes precedence over app-level."""
        app = AgenticApp(auth=_api_key_auth)

        @app.agent_endpoint(name="special", auth=_bearer_auth)
        async def special_agent(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"special": "data"}

        client = TestClient(app, raise_server_exceptions=False)

        # API key (app-level auth) should NOT work for this endpoint
        response = client.post(
            "/agent/special",
            json={"intent": "hi"},
            headers={"X-API-Key": VALID_API_KEY},
        )
        assert response.status_code == 401  # Missing Bearer

        # Bearer (endpoint-level auth) should work
        response = client.post(
            "/agent/special",
            json={"intent": "hi"},
            headers={"Authorization": f"Bearer {VALID_BEARER}"},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth user flows into AgentContext
# ---------------------------------------------------------------------------


class TestAuthUserInContext:
    """Verify that AuthUser populates AgentContext."""

    async def test_auth_user_populates_context_user_id(self) -> None:
        app = AgenticApp(auth=_api_key_auth)
        captured_context: list[AgentContext] = []

        @app.agent_endpoint(name="test")
        async def test_agent(intent: Intent, context: AgentContext) -> dict[str, Any]:
            captured_context.append(context)
            return {"user_id": context.user_id}

        response = await app.process_intent("hello", endpoint_name="test", auth_user=AuthUser(user_id="u1"))
        assert response.status == "completed"
        assert captured_context[0].user_id == "u1"
        assert "auth_user" in captured_context[0].metadata

    async def test_no_auth_user_leaves_context_user_id_none(self) -> None:
        app = AgenticApp()

        captured_context: list[AgentContext] = []

        @app.agent_endpoint(name="test")
        async def test_agent(intent: Intent, context: AgentContext) -> dict[str, Any]:
            captured_context.append(context)
            return {}

        await app.process_intent("hello", endpoint_name="test")
        assert captured_context[0].user_id is None
        assert "auth_user" not in captured_context[0].metadata
