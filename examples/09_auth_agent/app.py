"""Authentication example: API key-protected agent endpoints.

Demonstrates:
- ``APIKeyHeader`` security scheme for extracting API keys from headers
- ``Authenticator`` combining a scheme with a verification function
- Public endpoints (no auth) alongside protected endpoints
- Per-endpoint ``auth=`` configuration
- Authenticated user information available via ``context.user_id`` and ``context.metadata``

Run with:
    uvicorn examples.09_auth_agent.app:app --reload

Test with curl:
    # Public endpoint (no auth needed)
    curl -X POST http://127.0.0.1:8000/agent/info.public \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "What services are available?"}'

    # Protected endpoint WITHOUT auth (returns 401)
    curl -X POST http://127.0.0.1:8000/agent/info.protected \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show user details"}'

    # Protected endpoint WITH valid auth
    curl -X POST http://127.0.0.1:8000/agent/info.protected \\
        -H "Content-Type: application/json" \\
        -H "X-API-Key: alice-key-001" \\
        -d '{"intent": "Show user details"}'

    # Admin endpoint with admin key
    curl -X POST http://127.0.0.1:8000/agent/info.admin \\
        -H "Content-Type: application/json" \\
        -H "X-API-Key: admin-key-999" \\
        -d '{"intent": "Show all users"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi.app import AgenticApp
from agenticapi.interface.response import AgentResponse
from agenticapi.routing import AgentRouter
from agenticapi.security import APIKeyHeader, AuthCredentials, Authenticator, AuthUser

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# --- API key database (in production, use a real store) ---

API_KEYS: dict[str, dict[str, Any]] = {
    "alice-key-001": {"user_id": "user-1", "username": "alice", "roles": ("operator",)},
    "bob-key-002": {"user_id": "user-2", "username": "bob", "roles": ("operator",)},
    "admin-key-999": {"user_id": "admin-1", "username": "admin", "roles": ("admin", "operator")},
}


# --- Verify function ---


async def verify_api_key(credentials: AuthCredentials) -> AuthUser | None:
    """Look up an API key and return the associated user."""
    user_data = API_KEYS.get(credentials.credentials)
    if user_data is None:
        return None
    return AuthUser(
        user_id=user_data["user_id"],
        username=user_data["username"],
        roles=user_data["roles"],
    )


# --- Authenticator ---

api_key_auth = Authenticator(
    scheme=APIKeyHeader(name="X-API-Key"),
    verify=verify_api_key,
)


# --- Router ---

router = AgentRouter(prefix="info", tags=["info"])


@router.agent_endpoint(
    name="public",
    description="Public information (no auth required)",
    autonomy_level="auto",
)
async def public_info(intent: Intent, context: AgentContext) -> AgentResponse:
    """Public endpoint — accessible without authentication."""
    return AgentResponse(
        result={
            "services": ["info.public", "info.protected", "info.admin"],
            "message": "Welcome! Use an API key to access protected endpoints.",
        },
        reasoning="Public info — no authentication required",
    )


@router.agent_endpoint(
    name="protected",
    description="Protected user information (requires API key)",
    auth=api_key_auth,
    autonomy_level="auto",
)
async def protected_info(intent: Intent, context: AgentContext) -> AgentResponse:
    """Protected endpoint — requires a valid API key."""
    auth_user = context.metadata.get("auth_user")
    return AgentResponse(
        result={
            "user_id": context.user_id,
            "username": auth_user.username if auth_user else None,
            "roles": list(auth_user.roles) if auth_user else [],
            "message": f"Hello {auth_user.username if auth_user else 'user'}! You have access.",
        },
        reasoning=f"Authenticated as {context.user_id}",
    )


@router.agent_endpoint(
    name="admin",
    description="Admin information (requires admin API key)",
    auth=api_key_auth,
    autonomy_level="supervised",
)
async def admin_info(intent: Intent, context: AgentContext) -> AgentResponse:
    """Admin endpoint — requires API key with admin role."""
    auth_user = context.metadata.get("auth_user")
    roles = auth_user.roles if auth_user else ()

    if "admin" not in roles:
        return AgentResponse(
            result={"error": "Admin role required"},
            status="error",
            reasoning="User authenticated but lacks admin role",
        )

    return AgentResponse(
        result={
            "all_users": [
                {"user_id": v["user_id"], "username": v["username"], "roles": list(v["roles"])}
                for v in API_KEYS.values()
            ],
            "total_keys": len(API_KEYS),
        },
        reasoning=f"Admin access granted to {auth_user.username if auth_user else 'unknown'}",
    )


# --- App ---

app = AgenticApp(title="Auth Agent Example", version="0.1.0")
app.include_router(router)
