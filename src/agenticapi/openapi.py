"""OpenAPI schema generation and Swagger/ReDoc UI for AgenticAPI.

Generates an OpenAPI 3.1.0 specification from registered agent endpoints
and serves interactive documentation UIs, similar to FastAPI's /docs and /redoc.

Usage:
    app = AgenticApp(title="My Service", version="1.0.0")

    @app.agent_endpoint(name="orders", description="Manage orders")
    async def orders_agent(intent, context): ...

    # The following routes are auto-registered:
    #   GET /openapi.json  — OpenAPI schema
    #   GET /docs          — Swagger UI
    #   GET /redoc         — ReDoc UI
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from starlette.requests import Request

    from agenticapi.interface.endpoint import AgentEndpointDef

# ---------------------------------------------------------------------------
# Swagger UI and ReDoc HTML templates
# ---------------------------------------------------------------------------

_SWAGGER_UI_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>{title} - Swagger UI</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" type="text/css"
          href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
    <script>
    SwaggerUIBundle({{
        url: "{openapi_url}",
        dom_id: '#swagger-ui',
        presets: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIStandalonePreset
        ],
        layout: "StandaloneLayout"
    }});
    </script>
</body>
</html>"""

_REDOC_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>{title} - ReDoc</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700"
          rel="stylesheet">
    <style>body {{ margin: 0; padding: 0; }}</style>
</head>
<body>
    <redoc spec-url='{openapi_url}'></redoc>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Schema generation
# ---------------------------------------------------------------------------

_INTENT_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["intent"],
    "properties": {
        "intent": {
            "type": "string",
            "description": "Natural language intent describing what the user wants.",
            "examples": ["Show me recent orders", "Cancel order #1234"],
        },
        "session_id": {
            "type": "string",
            "description": "Optional session ID for multi-turn conversations.",
        },
        "context": {
            "type": "object",
            "description": "Optional additional context for the request.",
            "additionalProperties": True,
        },
    },
}

_AGENT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "result": {
            "description": "The primary output from the agent.",
        },
        "status": {
            "type": "string",
            "enum": ["completed", "pending_approval", "error", "clarification_needed"],
        },
        "generated_code": {
            "type": "string",
            "nullable": True,
            "description": "The code that was generated and executed (if LLM is active).",
        },
        "reasoning": {
            "type": "string",
            "nullable": True,
            "description": "The agent's reasoning for its response.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "execution_trace_id": {
            "type": "string",
            "nullable": True,
            "description": "Audit trace identifier for this execution.",
        },
        "follow_up_suggestions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "error": {
            "type": "string",
            "nullable": True,
        },
        "approval_request": {
            "type": "object",
            "nullable": True,
            "description": "Approval request details when status is pending_approval.",
        },
    },
}


def generate_openapi_schema(
    *,
    title: str,
    version: str,
    endpoints: dict[str, AgentEndpointDef],
    description: str = "",
) -> dict[str, Any]:
    """Generate an OpenAPI 3.1.0 schema from registered agent endpoints.

    Each agent endpoint becomes a POST operation at ``/agent/{name}``.

    Args:
        title: API title.
        version: API version string.
        endpoints: Dict of endpoint name to AgentEndpointDef.
        description: Optional API description.

    Returns:
        A complete OpenAPI 3.1.0 schema dict.
    """
    paths: dict[str, Any] = {}

    for name, endpoint_def in endpoints.items():
        path = f"/agent/{name}"
        tags = _extract_tags(name)

        # Build operation
        operation: dict[str, Any] = {
            "summary": endpoint_def.description or f"Agent endpoint: {name}",
            "operationId": f"agent_{name.replace('.', '_')}",
            "tags": tags,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": _INTENT_REQUEST_SCHEMA,
                    },
                },
            },
            "responses": {
                "200": {
                    "description": "Successful agent response.",
                    "content": {
                        "application/json": {
                            "schema": _AGENT_RESPONSE_SCHEMA,
                        },
                    },
                },
                "202": {
                    "description": "Approval required — the operation needs human approval before execution.",
                },
                "400": {
                    "description": "Bad request — missing or invalid intent.",
                },
                "403": {
                    "description": "Forbidden — intent scope or policy violation.",
                },
                "500": {
                    "description": "Internal server error.",
                },
            },
        }

        # Add endpoint metadata
        details: list[str] = []
        if endpoint_def.autonomy_level:
            details.append(f"**Autonomy level:** `{endpoint_def.autonomy_level}`")
        if endpoint_def.intent_scope:
            scope = endpoint_def.intent_scope
            if scope.allowed_intents:
                details.append(f"**Allowed intents:** `{', '.join(scope.allowed_intents)}`")
            if scope.denied_intents:
                details.append(f"**Denied intents:** `{', '.join(scope.denied_intents)}`")
        if endpoint_def.policies:
            policy_names = [type(p).__name__ for p in endpoint_def.policies]
            details.append(f"**Policies:** {', '.join(policy_names)}")
        if details:
            operation["description"] = "\n\n".join(details)

        paths[path] = {"post": operation}

    # Health endpoint
    paths["/health"] = {
        "get": {
            "summary": "Health check",
            "operationId": "health_check",
            "tags": ["system"],
            "responses": {
                "200": {
                    "description": "Application health status.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string", "enum": ["ok"]},
                                    "version": {"type": "string"},
                                    "endpoints": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }

    schema: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": version,
        },
        "paths": paths,
    }
    if description:
        schema["info"]["description"] = description

    return schema


def _extract_tags(name: str) -> list[str]:
    """Extract tags from a dotted endpoint name.

    ``"orders.query"`` -> ``["orders"]``
    ``"greeter"`` -> ``["default"]``
    """
    if "." in name:
        return [name.rsplit(".", 1)[0]]
    return ["default"]


# ---------------------------------------------------------------------------
# Route factories
# ---------------------------------------------------------------------------


def build_openapi_routes(
    *,
    title: str,
    version: str,
    endpoints: dict[str, AgentEndpointDef],
    description: str = "",
    openapi_url: str = "/openapi.json",
    docs_url: str = "/docs",
    redoc_url: str = "/redoc",
) -> list[Route]:
    """Build Starlette routes for OpenAPI schema and interactive docs.

    Args:
        title: API title.
        version: API version.
        endpoints: Registered agent endpoints.
        description: Optional API description.
        openapi_url: URL path for the OpenAPI JSON schema.
        docs_url: URL path for Swagger UI.
        redoc_url: URL path for ReDoc.

    Returns:
        List of Starlette Route objects to add to the app.
    """
    # Cache the schema so it's only generated once
    _schema_cache: dict[str, Any] = {}

    def _get_schema() -> dict[str, Any]:
        if "schema" not in _schema_cache:
            _schema_cache["schema"] = generate_openapi_schema(
                title=title,
                version=version,
                endpoints=endpoints,
                description=description,
            )
        result: dict[str, Any] = _schema_cache["schema"]
        return result

    async def openapi_handler(request: Request) -> JSONResponse:
        return JSONResponse(_get_schema())

    async def swagger_handler(request: Request) -> HTMLResponse:
        html = _SWAGGER_UI_HTML.format(title=title, openapi_url=openapi_url)
        return HTMLResponse(html)

    async def redoc_handler(request: Request) -> HTMLResponse:
        html = _REDOC_HTML.format(title=title, openapi_url=openapi_url)
        return HTMLResponse(html)

    return [
        Route(openapi_url, openapi_handler, methods=["GET"]),
        Route(docs_url, swagger_handler, methods=["GET"]),
        Route(redoc_url, redoc_handler, methods=["GET"]),
    ]
