"""REST interoperability example: FastAPI-style schemas and mixed ASGI apps.

Real production AgenticAPI deployments rarely live alone. They sit
next to an existing REST API (health checks, admin UIs, billing
webhooks) and grow out of a migration from a pre-existing service.
This example shows the three patterns that make that integration
painless:

    1. ``response_model`` on agent endpoints — exactly like FastAPI's
       ``response_model=``. The Pydantic model is validated on every
       handler return *and* shows up in the auto-generated OpenAPI
       schema so Swagger UI renders the same typed response shape
       you'd get from a FastAPI app.

    2. ``expose_as_rest`` — generate plain ``GET /rest/{name}`` and
       ``POST /rest/{name}`` routes from every agent endpoint, so
       clients that can't speak the native ``POST /agent/{name}``
       intent API (legacy SDKs, curl one-liners in a runbook, a
       Grafana HTTP data source) still work without any extra code
       on your side.

    3. **Mounted sub-apps** — via ``app.add_routes([Mount(...)])``,
       mount a plain Starlette (or FastAPI) sub-app at a path inside
       the AgenticAPI service. Handy when you're migrating an
       existing API one endpoint at a time, or when you want to keep
       a legacy billing-webhook receiver running next to the new
       agent endpoints. This example uses a Starlette ``Mount`` so
       it runs without any FastAPI install, but the same pattern
       works identically with ``FastAPI()`` in place of
       ``Starlette(...)``.

Domain: a tiny **payments API** with three outcomes:

* ``payments.create`` — a typed create-a-payment endpoint that
  validates its return through the ``Payment`` Pydantic model, so
  a client receives the same shape whether they hit the native
  intent API or the REST compat layer.
* ``payments.list`` — a typed list endpoint whose schema is
  published in OpenAPI as ``PaymentList``.
* ``payments.get`` — a typed read-by-id endpoint that looks up a
  payment and returns a ``Payment``.

And a legacy ``/legacy`` Starlette sub-app with a plain REST
``GET /legacy/ping`` and ``GET /legacy/webhooks/health`` — mounted
inside the same AgenticAPI process so operators hit a single
service.

Features demonstrated:

* ``response_model`` on agent endpoints (Pydantic validation +
  OpenAPI schema publication)
* ``expose_as_rest`` for GET/POST REST routes that share the same
  handlers and the same typed responses
* ``app.add_routes([Mount(...)])`` for running a Starlette sub-app
  next to agent endpoints in the same process
* The auto-generated ``/openapi.json`` lists the Pydantic models
  under ``components/schemas`` and references them from each
  endpoint's ``200 OK`` response shape
* Everything works without a FastAPI install — the mounted sub-app
  is a plain Starlette instance for portability. Swap in ``FastAPI()``
  and it works identically.

No LLM or API key is required.

Run with::

    uvicorn examples.18_rest_interop.app:app --reload

Test with curl::

    # --- Native intent API (the AgenticAPI-native path) ---

    # Create a payment
    curl -X POST http://127.0.0.1:8000/agent/payments.create \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "charge alice $42 for a latte"}'

    # List payments
    curl -X POST http://127.0.0.1:8000/agent/payments.list \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "show recent payments"}'

    # Get a payment by id (id is encoded in the intent for the demo)
    curl -X POST http://127.0.0.1:8000/agent/payments.get \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "get payment pay-001"}'

    # --- REST compat layer (same handlers, GET/POST surface) ---

    # GET: query string is the intent body
    curl "http://127.0.0.1:8000/rest/payments.list?query=show+all+payments"

    # POST: JSON body with an "intent" field (clients that already speak REST)
    curl -X POST http://127.0.0.1:8000/rest/payments.create \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "charge bob $19 for a book"}'

    # --- Mounted legacy Starlette sub-app ---

    curl http://127.0.0.1:8000/legacy/ping
    curl http://127.0.0.1:8000/legacy/webhooks/health

    # --- Standard framework routes (all still present) ---

    curl http://127.0.0.1:8000/health
    curl http://127.0.0.1:8000/capabilities
    curl http://127.0.0.1:8000/openapi.json | python -m json.tool | head -60
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from agenticapi import AgenticApp, Intent
from agenticapi.interface.compat.rest import expose_as_rest
from agenticapi.routing import AgentRouter

if TYPE_CHECKING:
    from starlette.requests import Request

    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# 1. Typed response models — these end up in the OpenAPI schema
# ---------------------------------------------------------------------------
# These are plain Pydantic models — the exact same shape you'd use
# with FastAPI's ``response_model=``. Because the agent_endpoint
# decorator accepts a ``response_model`` parameter, the framework
# validates handler returns against these at runtime and publishes
# the schemas under ``components/schemas`` in ``/openapi.json``.


class Payment(BaseModel):
    """A payment record, validated on every handler return."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique payment identifier")
    customer: str = Field(..., description="Customer name or id")
    amount_cents: int = Field(..., ge=0, description="Payment amount in whole cents")
    currency: str = Field("USD", description="ISO-4217 currency code")
    memo: str = Field("", description="Free-form description")
    created_at: datetime = Field(..., description="When the payment was created (UTC)")


class PaymentList(BaseModel):
    """List-payments response envelope."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(..., ge=0)
    payments: list[Payment]


# ---------------------------------------------------------------------------
# 2. In-memory payment store
# ---------------------------------------------------------------------------
# Seeded with two payments so ``payments.list`` and ``payments.get``
# return something useful on the first request.

_PAYMENTS: dict[str, Payment] = {
    "pay-001": Payment(
        id="pay-001",
        customer="alice",
        amount_cents=4_200,
        currency="USD",
        memo="Latte",
        created_at=datetime.now(tz=UTC),
    ),
    "pay-002": Payment(
        id="pay-002",
        customer="bob",
        amount_cents=1_900,
        currency="USD",
        memo="Book",
        created_at=datetime.now(tz=UTC),
    ),
}


def _next_id() -> str:
    return f"pay-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# 3. Tiny intent parser
# ---------------------------------------------------------------------------
# The example deliberately skips the LLM path so it runs without any
# API keys. These regex helpers give deterministic behaviour so the
# test suite and the curl walkthrough can make exact assertions.

_AMOUNT_RE = re.compile(r"\$?(\d+(?:\.\d+)?)")
_CUSTOMER_RE = re.compile(r"\b(alice|bob|charlie|diana)\b", re.IGNORECASE)
_ID_RE = re.compile(r"\b(pay-[a-z0-9-]+)\b", re.IGNORECASE)


def _parse_amount_cents(text: str) -> int:
    match = _AMOUNT_RE.search(text)
    if not match:
        return 0
    return int(float(match.group(1)) * 100)


def _parse_customer(text: str) -> str:
    match = _CUSTOMER_RE.search(text)
    return match.group(1).lower() if match else "unknown"


def _parse_payment_id(text: str) -> str | None:
    match = _ID_RE.search(text)
    return match.group(1).lower() if match else None


# ---------------------------------------------------------------------------
# 4. Application
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Payments API (REST Interop Example)",
    version="0.1.0",
    description=(
        "Typed payments API showing response_model, expose_as_rest, and "
        "mount_in_agenticapi — the three integration primitives that let "
        "AgenticAPI slot into an existing FastAPI/Starlette stack."
    ),
)


# ---------------------------------------------------------------------------
# 5. Agent endpoints with typed response models
# ---------------------------------------------------------------------------

payments = AgentRouter(prefix="payments", tags=["payments"])


@payments.agent_endpoint(
    name="create",
    description="Create a new payment and return it as a validated Payment model",
    autonomy_level="auto",
    response_model=Payment,
)
async def create_payment(intent: Intent, context: AgentContext) -> dict:
    """Parse the intent, build a Payment, and return a plain dict.

    The framework runs the dict through ``Payment.model_validate``
    (because ``response_model=Payment`` is set on the decorator)
    and returns the serialized form to the client. If the dict
    doesn't match the model, the handler raises a validation error
    that the framework maps to HTTP 500 — the same behaviour as
    FastAPI's ``response_model``.
    """
    customer = _parse_customer(intent.raw)
    amount_cents = _parse_amount_cents(intent.raw) or 1_000  # default $10
    payment = Payment(
        id=_next_id(),
        customer=customer,
        amount_cents=amount_cents,
        currency="USD",
        memo=intent.raw[:120],
        created_at=datetime.now(tz=UTC),
    )
    _PAYMENTS[payment.id] = payment
    return payment.model_dump(mode="json")


@payments.agent_endpoint(
    name="list",
    description="List all payments; returns a PaymentList response model",
    autonomy_level="auto",
    response_model=PaymentList,
)
async def list_payments(intent: Intent, context: AgentContext) -> dict:
    """Return every known payment wrapped in a ``PaymentList`` envelope."""
    items = list(_PAYMENTS.values())
    envelope = PaymentList(count=len(items), payments=items)
    return envelope.model_dump(mode="json")


@payments.agent_endpoint(
    name="get",
    description="Look up a single payment by id; returns a Payment or 404",
    autonomy_level="auto",
    response_model=Payment,
)
async def get_payment(intent: Intent, context: AgentContext) -> dict:
    """Look up a payment by id encoded in the intent.

    The demo parses ``pay-xxxxxxxx`` out of the intent text so both the
    native ``POST /agent/payments.get {"intent": "get pay-001"}`` API
    and the REST compat ``GET /rest/payments.get?query=get+pay-001``
    API route to the same handler.
    """
    payment_id = _parse_payment_id(intent.raw)
    if not payment_id or payment_id not in _PAYMENTS:
        # Return an empty Payment sentinel so the demo stays simple;
        # a real app would raise a typed NotFoundError that maps to 404.
        return {
            "id": payment_id or "unknown",
            "customer": "unknown",
            "amount_cents": 0,
            "currency": "USD",
            "memo": f"no payment matching intent={intent.raw!r}",
            "created_at": datetime.now(tz=UTC).isoformat(),
        }
    return _PAYMENTS[payment_id].model_dump(mode="json")


app.include_router(payments)


# ---------------------------------------------------------------------------
# 6. REST compat layer — GET/POST on /rest/{name}
# ---------------------------------------------------------------------------
# Every registered agent endpoint now *also* has a plain REST shape:
#
#     GET  /rest/payments.list?query=show+payments
#     POST /rest/payments.create  with JSON body {"intent": "..."}
#
# Handlers and response models are shared — the REST layer routes
# the GET query or POST body through ``process_intent`` and serialises
# the same typed result.

app.add_routes(expose_as_rest(app, prefix="/rest"))


# ---------------------------------------------------------------------------
# 7. Mounted Starlette sub-app (works for any ASGI app, including FastAPI)
# ---------------------------------------------------------------------------
# Simulates a legacy service that hasn't been ported to agent endpoints
# yet. The sub-app is a plain ``Starlette`` instance so the example
# runs without the ``fastapi`` package installed, but the same pattern
# works identically when you swap ``Starlette(...)`` for ``FastAPI(...)``.
#
# ``app.add_routes([Mount(...)])`` is the recommended way to attach a
# sub-app to an AgenticApp: the ``Mount`` primitive comes from
# Starlette, and AgenticApp simply appends extra routes to its
# internal routing table when it builds the underlying Starlette app.


async def legacy_ping(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "service": "legacy-payments",
            "message": "still running, still useful",
        }
    )


async def legacy_webhook_health(request: Request) -> JSONResponse:
    """Fake legacy webhook receiver — still needed by an upstream system."""
    return JSONResponse({"ok": True, "webhook_receiver": "billing-v1"})


legacy_app = Starlette(
    routes=[
        Route("/ping", legacy_ping, methods=["GET"]),
        Route("/webhooks/health", legacy_webhook_health, methods=["GET"]),
    ]
)

app.add_routes([Mount("/legacy", app=legacy_app)])
