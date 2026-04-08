# OpenAPI & Swagger

Every AgenticAPI app automatically serves OpenAPI documentation — no configuration needed.

## Auto-Generated Routes

| Route | What it serves |
|---|---|
| `GET /openapi.json` | OpenAPI 3.1.0 JSON schema |
| `GET /docs` | Swagger UI (interactive) |
| `GET /redoc` | ReDoc UI |

The schema includes every registered agent endpoint as a `POST /agent/{name}` operation, with request/response schemas, intent scope metadata, policy names, and autonomy levels.

## Customization

```python
app = AgenticApp(
    title="My API",
    version="2.0.0",
    description="My agent-powered service",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/schema.json",
)
```

## Disabling Docs

```python
app = AgenticApp(openapi_url=None)  # Disables all doc routes
```

## Schema Contents

Each agent endpoint generates:

- **Operation** with summary from endpoint `description`
- **Tags** derived from dotted names (`orders.query` -> tag `orders`)
- **Request body** schema: `intent` (required string), `session_id` (optional), `context` (optional object)
- **Response** schema: `result`, `status`, `generated_code`, `reasoning`, `confidence`, `execution_trace_id`, `follow_up_suggestions`, `error`, `approval_request`
- **HTTP status codes**: 200 (success), 202 (approval required), 400 (bad request), 403 (policy violation), 500 (server error)
- **Metadata** in description: autonomy level, intent scope patterns, attached policy names
