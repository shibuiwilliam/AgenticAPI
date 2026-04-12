# REST Compatibility

AgenticAPI can coexist with existing FastAPI/Starlette apps and expose agent endpoints
as conventional REST routes. Three patterns cover the common integration needs:

1. **Mount a Starlette / FastAPI sub-app inside AgenticAPI** — run legacy REST routes
   next to agent endpoints in the same process
2. **Mount AgenticAPI inside a FastAPI app** — keep your existing FastAPI service as
   the outer shell and add agent endpoints as a sub-application
3. **Expose agent endpoints as REST routes** — generate `GET /rest/{name}?query=...`
   and `POST /rest/{name}` handlers that share the same handlers (and typed response
   models) as the native intent API

A runnable end-to-end example covering all three patterns lives at
[`18_rest_interop`](../getting-started/examples.md#18-rest-interop-no-llm-deterministic-regex-parsing).

## 1. Mount a Starlette or FastAPI sub-app inside AgenticAPI

Attach any ASGI sub-app at a path inside an `AgenticApp` using `app.add_routes()` with
Starlette's standard `Mount` primitive:

```python
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse

from agenticapi import AgenticApp

async def legacy_ping(request):
    return JSONResponse({"ok": True, "service": "legacy"})

legacy_app = Starlette(routes=[Route("/ping", legacy_ping)])

app = AgenticApp(title="My Service")
app.add_routes([Mount("/legacy", app=legacy_app)])
# Legacy routes available at /legacy/ping, next to /agent/{name}, /health, /docs, ...
```

`Mount` accepts any ASGI app, so replacing `Starlette(...)` with `FastAPI()` is a
one-line change and produces identical behaviour.

## 2. Mount AgenticAPI inside an existing FastAPI app

When your outer service is already a FastAPI app, use `mount_fastapi` to slot an
`AgenticApp` in as a sub-application:

```python
from fastapi import FastAPI
from agenticapi import AgenticApp
from agenticapi.interface.compat import mount_fastapi

outer = FastAPI()
agent_app = AgenticApp(title="Agent Sub-Service")

mount_fastapi(agent_app, outer, path="/agent")
# Agent endpoints now available at /agent/agent/{name}
```

Because `AgenticApp` is itself an ASGI application, FastAPI's `mount()` accepts it
directly — `mount_fastapi` is a thin wrapper that adds structured logging so you can
see the mount happen at startup.

## 3. Expose agent endpoints as REST routes

`expose_as_rest` generates `GET /rest/{name}?query=...` and `POST /rest/{name}` routes
for every registered agent endpoint, sharing the same handlers and the same typed
response models:

```python
from agenticapi import AgenticApp
from agenticapi.interface.compat import expose_as_rest, RESTCompat

app = AgenticApp(title="My Service")

@app.agent_endpoint(name="orders", response_model=OrderList)
async def orders(intent, context):
    ...

# One-liner that generates a Route per agent endpoint
app.add_routes(expose_as_rest(app, prefix="/rest"))

# Or use the class directly when you need to customize
rest = RESTCompat(app, prefix="/rest")
app.add_routes(rest.generate_routes())
```

For each agent endpoint this generates:

- `GET /rest/{name}?query=...` — query string becomes the intent body
- `POST /rest/{name}` — JSON body with an `intent` field

Both paths route through the same handler as the native `POST /agent/{name}` API, so
the typed `response_model=` return shape is identical. Clients that speak REST but not
AgenticAPI's intent API can drive every endpoint unchanged, and OpenAPI schemas
published under `components/schemas` stay in sync.

## Using `response_model` for typed REST responses

`response_model` on an agent endpoint works the same way it does in FastAPI: the
handler returns a dict (or a model instance), the framework validates it against the
declared model, and the schema is published in `/openapi.json`. The REST compat layer
serializes the validated result in its standard envelope shape, so a REST client gets
the same type guarantees as a native intent client.

```python
from pydantic import BaseModel
from agenticapi import AgenticApp, Intent

class Payment(BaseModel):
    id: str
    amount_cents: int
    currency: str = "USD"

app = AgenticApp()

@app.agent_endpoint(name="payments.create", response_model=Payment)
async def create_payment(intent: Intent, context) -> dict:
    return {"id": "pay-001", "amount_cents": 4200, "currency": "USD"}

app.add_routes(expose_as_rest(app, prefix="/rest"))
```

A client can now hit either `POST /agent/payments.create` with a JSON `intent` body or
`GET /rest/payments.create?query=...` and receive an identically-shaped response. The
Swagger UI at `/docs` shows the `Payment` schema for both.
