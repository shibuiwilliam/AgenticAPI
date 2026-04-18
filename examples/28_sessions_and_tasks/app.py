"""Sessions and Background Tasks example: a multi-turn support chatbot.

Demonstrates two features that have no dedicated example elsewhere:

1. **Multi-turn sessions** -- the framework's ``SessionManager``
   tracks conversation history across requests. Clients send
   ``"session_id": "..."`` in the JSON body; the framework creates
   or resumes the session and accumulates turns automatically. The
   handler reads prior context from ``context.metadata["session"]``
   to give contextual replies.

2. **Background tasks** -- ``AgentTasks`` (the agent equivalent of
   FastAPI's ``BackgroundTasks``) lets handlers schedule work that
   runs *after* the HTTP response is sent. The example logs every
   interaction to an in-memory audit list and sends a "notification"
   when the conversation exceeds a turn threshold.

Additionally, the example shows **all four authentication schemes**
side by side (``APIKeyHeader``, ``APIKeyQuery``, ``HTTPBearer``,
``HTTPBasic``) so you can pick the one that fits your deployment.

No LLM or API key required.

Run with:
    uvicorn examples.28_sessions_and_tasks.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.28_sessions_and_tasks.app:app

Test with curl:
    # 1. Start a conversation (no session_id -> new session created)
    curl -X POST http://127.0.0.1:8000/agent/chat \
        -H "Content-Type: application/json" \
        -d '{"intent": "I need help with my order"}'

    # 2. Continue the conversation (use session_id from step 1)
    curl -X POST http://127.0.0.1:8000/agent/chat \
        -H "Content-Type: application/json" \
        -d '{"intent": "The order number is ORD-12345", "session_id": "<session_id>"}'

    # 3. Ask for history (same session)
    curl -X POST http://127.0.0.1:8000/agent/chat.history \
        -H "Content-Type: application/json" \
        -d '{"intent": "show history", "session_id": "<session_id>"}'

    # 4. View background task log
    curl -X POST http://127.0.0.1:8000/agent/chat.tasks \
        -H "Content-Type: application/json" \
        -d '{"intent": "show task log"}'

    # 5. Auth with API key in header
    curl -X POST http://127.0.0.1:8000/agent/chat.secure_header \
        -H "Content-Type: application/json" \
        -H "X-API-Key: demo-key" \
        -d '{"intent": "secure request via header key"}'

    # 6. Auth with API key in query string
    curl -X POST "http://127.0.0.1:8000/agent/chat.secure_query?api_key=demo-key" \
        -H "Content-Type: application/json" \
        -d '{"intent": "secure request via query param"}'

    # 7. Auth with Bearer token
    curl -X POST http://127.0.0.1:8000/agent/chat.secure_bearer \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer demo-token" \
        -d '{"intent": "secure request via bearer"}'

    # 8. Auth with HTTP Basic
    curl -X POST http://127.0.0.1:8000/agent/chat.secure_basic \
        -u "alice:password123" \
        -H "Content-Type: application/json" \
        -d '{"intent": "secure request via basic auth"}'
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agenticapi import AgenticApp, AgentResponse, AgentRouter, Intent
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
    from agenticapi.interface.tasks import AgentTasks
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# In-memory background task log (simulates a real audit/notification system)
# ---------------------------------------------------------------------------

_task_log: list[dict[str, Any]] = []

TURN_NOTIFICATION_THRESHOLD = 3


async def log_interaction(*, session_id: str, intent: str, timestamp: str) -> None:
    """Background task: log every interaction after the response is sent."""
    _task_log.append(
        {
            "type": "interaction_logged",
            "session_id": session_id,
            "intent": intent,
            "logged_at": timestamp,
        }
    )


async def send_long_conversation_alert(*, session_id: str, turn_count: int) -> None:
    """Background task: alert when a conversation exceeds the threshold."""
    _task_log.append(
        {
            "type": "long_conversation_alert",
            "session_id": session_id,
            "turn_count": turn_count,
            "alerted_at": datetime.now(tz=UTC).isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# Multi-scheme authentication
# ---------------------------------------------------------------------------

# Four auth schemes — each extracts credentials from a different location.
# auto_error=True (the default) makes the scheme raise 401 if credentials
# are missing, which is what you want for secured endpoints.
_header_scheme = APIKeyHeader(name="X-API-Key")
_query_scheme = APIKeyQuery(name="api_key")
_bearer_scheme = HTTPBearer()
_basic_scheme = HTTPBasic()

_VALID_API_KEYS = {"demo-key", "admin-key"}
_VALID_TOKENS = {"demo-token", "admin-token"}
_VALID_USERS = {"alice": "password123", "bob": "secret456"}


async def multi_scheme_verify(credentials: AuthCredentials) -> AuthUser | None:
    """Verify credentials from any of the four supported schemes.

    This is the single verify function that handles all auth methods.
    The framework tries each scheme in order; the first one that
    extracts credentials passes them here.
    """
    scheme = credentials.scheme

    # Both APIKeyHeader and APIKeyQuery use scheme="apikey"
    if scheme == "apikey" and credentials.credentials in _VALID_API_KEYS:
        return AuthUser(user_id="key-user", username="api-key-holder", roles=("user",))

    # HTTPBearer uses scheme="bearer"
    if scheme == "bearer" and credentials.credentials in _VALID_TOKENS:
        return AuthUser(user_id="token-user", username="bearer-holder", roles=("user",))

    # HTTPBasic uses scheme="basic"; credentials is "username:password"
    if scheme == "basic":
        parts = credentials.credentials.split(":", 1)
        if len(parts) == 2:
            username, password = parts
            if _VALID_USERS.get(username) == password:
                return AuthUser(user_id=username, username=username, roles=("user",))

    return None


# Each scheme tries to extract credentials from the request.
# We compose them by creating separate Authenticator instances
# and trying each in a Depends chain.

# Each scheme gets its own Authenticator — attach to endpoints via auth=.
header_auth = Authenticator(scheme=_header_scheme, verify=multi_scheme_verify)
query_auth = Authenticator(scheme=_query_scheme, verify=multi_scheme_verify)
bearer_auth = Authenticator(scheme=_bearer_scheme, verify=multi_scheme_verify)
basic_auth = Authenticator(scheme=_basic_scheme, verify=multi_scheme_verify)


# ---------------------------------------------------------------------------
# Session-aware response helpers
# ---------------------------------------------------------------------------

# Simple intent-keyword responses (no LLM needed)
_RESPONSES: dict[str, str] = {
    "order": "I can help with your order. Could you share the order number?",
    "shipping": "Shipping typically takes 3-5 business days. Need tracking info?",
    "return": "Returns are accepted within 30 days. I'll start the process for you.",
    "refund": "Refund requests are processed in 5-7 business days after we receive the item.",
    "cancel": "I can cancel your order if it hasn't shipped yet. What's the order number?",
}

_DEFAULT_RESPONSE = "I'm here to help! You can ask about orders, shipping, returns, refunds, or cancellations."


def _build_reply(intent_raw: str, prior_turns: int) -> str:
    """Generate a response based on keywords and conversation context."""
    lowered = intent_raw.lower()

    # Check for order number pattern
    if "ord-" in lowered:
        return f"Got it, I found order {intent_raw.split()[-1].upper()}. What do you need help with?"

    for keyword, response in _RESPONSES.items():
        if keyword in lowered:
            if prior_turns > 0:
                return f"Still helping you out! {response}"
            return response

    if prior_turns > 0:
        return f"We've been chatting for {prior_turns} turns. {_DEFAULT_RESPONSE}"
    return _DEFAULT_RESPONSE


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

router = AgentRouter(prefix="chat", tags=["chat"])


@router.agent_endpoint(
    name="chat",
    description="Multi-turn support chatbot. Send session_id to continue a conversation.",
    autonomy_level="auto",
)
async def chat(intent: Intent, context: AgentContext, tasks: AgentTasks) -> AgentResponse:
    """Handle a chat turn with session context and background logging.

    The framework automatically:
    - Creates or resumes a session based on ``session_id`` in the request body.
    - Injects the session into ``context.metadata["session"]``.
    - Records the turn in session history after the handler returns.
    - Injects ``AgentTasks`` for post-response background work.
    """
    session = context.metadata.get("session")
    session_id = context.session_id or "unknown"
    prior_turns = len(session.history) if session else 0

    reply = _build_reply(intent.raw, prior_turns)

    # Schedule background tasks (run AFTER the response is sent)
    tasks.add_task(
        log_interaction,
        session_id=session_id,
        intent=intent.raw,
        timestamp=datetime.now(tz=UTC).isoformat(),
    )
    if prior_turns >= TURN_NOTIFICATION_THRESHOLD:
        tasks.add_task(
            send_long_conversation_alert,
            session_id=session_id,
            turn_count=prior_turns + 1,
        )

    return AgentResponse(
        result={
            "reply": reply,
            "session_id": session_id,
            "turn": prior_turns + 1,
            "background_tasks_scheduled": tasks.pending_count,
        },
        reasoning=f"Turn {prior_turns + 1} in session {session_id}",
    )


@router.agent_endpoint(
    name="history",
    description="View conversation history for a session.",
    autonomy_level="auto",
)
async def history(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Return the conversation history for the current session."""
    session = context.metadata.get("session")
    session_id = context.session_id or "unknown"

    if session is None or not session.history:
        return {"session_id": session_id, "turns": 0, "history": []}

    return {
        "session_id": session_id,
        "turns": len(session.history),
        "history": session.history,
    }


@router.agent_endpoint(
    name="tasks",
    description="View the background task execution log.",
    autonomy_level="auto",
)
async def task_log(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Return the background task log (interactions + alerts)."""
    return {
        "total_logged": len(_task_log),
        "interactions": [e for e in _task_log if e["type"] == "interaction_logged"],
        "alerts": [e for e in _task_log if e["type"] == "long_conversation_alert"],
    }


def _auth_response(intent: Intent, context: AgentContext, scheme_name: str) -> dict[str, Any]:
    """Shared response builder for all auth endpoints."""
    user = context.metadata.get("auth_user")
    return {
        "reply": f"Hello {user.username if user else 'unknown'}! Authenticated via {scheme_name}.",
        "auth_scheme": scheme_name,
        "user": {"user_id": user.user_id, "username": user.username, "roles": list(user.roles)} if user else None,
        "intent": intent.raw,
    }


@router.agent_endpoint(
    name="secure_header",
    description="Secured with APIKeyHeader (X-API-Key header).",
    autonomy_level="auto",
    auth=header_auth,
)
async def secure_header(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Endpoint secured with an API key in the ``X-API-Key`` header."""
    return _auth_response(intent, context, "APIKeyHeader")


@router.agent_endpoint(
    name="secure_query",
    description="Secured with APIKeyQuery (?api_key= query parameter).",
    autonomy_level="auto",
    auth=query_auth,
)
async def secure_query(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Endpoint secured with an API key in a query parameter."""
    return _auth_response(intent, context, "APIKeyQuery")


@router.agent_endpoint(
    name="secure_bearer",
    description="Secured with HTTPBearer (Authorization: Bearer <token>).",
    autonomy_level="auto",
    auth=bearer_auth,
)
async def secure_bearer(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Endpoint secured with a Bearer token."""
    return _auth_response(intent, context, "HTTPBearer")


@router.agent_endpoint(
    name="secure_basic",
    description="Secured with HTTPBasic (Authorization: Basic <base64>).",
    autonomy_level="auto",
    auth=basic_auth,
)
async def secure_basic(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Endpoint secured with HTTP Basic authentication."""
    return _auth_response(intent, context, "HTTPBasic")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Sessions & Background Tasks",
    version="0.1.0",
    description=(
        "Multi-turn support chatbot demonstrating session management, "
        "background tasks (AgentTasks), and multi-scheme authentication."
    ),
)
app.include_router(router)
