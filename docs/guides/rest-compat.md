# REST Compatibility

AgenticAPI can coexist with existing FastAPI/Starlette apps and expose agent endpoints as conventional REST routes.

## Mount FastAPI Inside AgenticAPI

```python
from agenticapi.interface.compat import mount_in_agenticapi

mount_in_agenticapi(agenticapi_app, fastapi_app, path="/api/v1")
# FastAPI routes available at /api/v1/*
```

## Mount AgenticAPI Inside FastAPI

```python
from agenticapi.interface.compat import mount_fastapi

mount_fastapi(agenticapi_app, fastapi_app, path="/agent")
# Agent endpoints available at /agent/agent/{name}
```

## Expose Agent Endpoints as REST

```python
from agenticapi.interface.compat import expose_as_rest, RESTCompat

# Quick function
routes = expose_as_rest(app, prefix="/rest")

# Or use RESTCompat class directly
rest = RESTCompat(app, prefix="/rest")
routes = rest.generate_routes()
```

This generates for each agent endpoint:

- `GET /rest/{name}?query=...` — Maps query string to a read intent
- `POST /rest/{name}` — Maps JSON body to a write intent
