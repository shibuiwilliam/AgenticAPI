"""REST compatibility layer for agent endpoints.

Generates conventional REST-style routes from agent endpoints,
allowing the same agent to be accessed via both the native intent
API and standard REST patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

    from agenticapi.app import AgenticApp
    from agenticapi.interface.endpoint import AgentEndpointDef

logger = structlog.get_logger(__name__)


_MAX_INTENT_LENGTH = 10_000  # Maximum allowed intent string length


class RESTCompat:
    """Generate REST-style routes from agent endpoints.

    Maps agent endpoints to conventional REST paths:
        agent_endpoint("orders") -> GET /rest/orders, POST /rest/orders

    GET requests map query parameters to a "read" intent.
    POST requests map JSON body fields to a "write" intent.

    Example:
        app = AgenticApp()

        @app.agent_endpoint(name="orders")
        async def orders_agent(intent, context):
            ...

        rest_routes = expose_as_rest(app, prefix="/rest")
        # Generates:
        #   GET /rest/orders?query=show+orders -> read intent
        #   POST /rest/orders -> write intent from JSON body
    """

    def __init__(self, app: AgenticApp, *, prefix: str = "/rest") -> None:
        """Initialize REST compatibility layer.

        Args:
            app: The AgenticApp to generate REST routes for.
            prefix: URL prefix for REST routes.
        """
        self._app = app
        self._prefix = prefix.rstrip("/")

    def generate_routes(self) -> list[Route]:
        """Generate Starlette Routes for all registered agent endpoints.

        Returns:
            List of Starlette Route objects for REST access.
        """
        routes: list[Route] = []
        for name, endpoint_def in self._app._endpoints.items():
            path = f"{self._prefix}/{name}"
            get_handler = self._create_get_handler(name, endpoint_def)
            post_handler = self._create_post_handler(name, endpoint_def)
            routes.append(Route(path, get_handler, methods=["GET"]))
            routes.append(Route(path, post_handler, methods=["POST"]))

        logger.info(
            "rest_compat_routes_generated",
            endpoint_count=len(self._app._endpoints),
            prefix=self._prefix,
        )
        return routes

    def _create_get_handler(
        self,
        name: str,
        endpoint_def: AgentEndpointDef,
    ) -> Callable[..., Any]:
        """Create a GET handler that maps query params to a read intent.

        Args:
            name: The endpoint name.
            endpoint_def: The endpoint definition.

        Returns:
            An async Starlette handler.
        """

        async def handler(request: Request) -> Response:
            query = request.query_params.get("query", "")
            if not query:
                # Build intent from all query params
                params = dict(request.query_params)
                query = f"read {name}: {params}" if params else f"read {name}"

            if len(query) > _MAX_INTENT_LENGTH:
                return JSONResponse(
                    {"error": f"Intent too long ({len(query)} chars, max {_MAX_INTENT_LENGTH})", "status": "error"},
                    status_code=400,
                )

            try:
                response = await self._app.process_intent(
                    query,
                    endpoint_name=name,
                    session_id=request.query_params.get("session_id"),
                )
                # File response passthrough
                from starlette.responses import Response

                if isinstance(response, Response):
                    return response
                from agenticapi.interface.response import ResponseFormatter

                formatter = ResponseFormatter()
                return JSONResponse(formatter.format_json(response))
            except Exception as exc:
                from agenticapi.exceptions import EXCEPTION_STATUS_MAP, AgenticAPIError

                status_code = EXCEPTION_STATUS_MAP.get(type(exc), 500) if isinstance(exc, AgenticAPIError) else 500
                return JSONResponse(
                    {"error": str(exc), "status": "error"},
                    status_code=status_code,
                )

        return handler

    def _create_post_handler(
        self,
        name: str,
        endpoint_def: AgentEndpointDef,
    ) -> Callable[..., Any]:
        """Create a POST handler that maps JSON body to a write intent.

        Args:
            name: The endpoint name.
            endpoint_def: The endpoint definition.

        Returns:
            An async Starlette handler.
        """

        async def handler(request: Request) -> Response:
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    {"error": "Invalid JSON body", "status": "error"},
                    status_code=400,
                )

            intent = body.get("intent", "")
            if not intent:
                intent = f"write {name}: {body}"

            if len(intent) > _MAX_INTENT_LENGTH:
                return JSONResponse(
                    {"error": f"Intent too long ({len(intent)} chars, max {_MAX_INTENT_LENGTH})", "status": "error"},
                    status_code=400,
                )

            session_id = body.get("session_id")

            try:
                response = await self._app.process_intent(
                    intent,
                    endpoint_name=name,
                    session_id=session_id,
                )
                # File response passthrough
                from starlette.responses import Response

                if isinstance(response, Response):
                    return response
                from agenticapi.interface.response import ResponseFormatter

                formatter = ResponseFormatter()
                return JSONResponse(formatter.format_json(response))
            except Exception as exc:
                from agenticapi.exceptions import EXCEPTION_STATUS_MAP, AgenticAPIError

                status_code = EXCEPTION_STATUS_MAP.get(type(exc), 500) if isinstance(exc, AgenticAPIError) else 500
                return JSONResponse(
                    {"error": str(exc), "status": "error"},
                    status_code=status_code,
                )

        return handler


def expose_as_rest(app: AgenticApp, *, prefix: str = "/rest") -> list[Route]:
    """Convenience function to generate REST routes for all agent endpoints.

    Args:
        app: The AgenticApp to generate routes for.
        prefix: URL prefix for REST routes.

    Returns:
        List of Starlette Route objects.
    """
    compat = RESTCompat(app, prefix=prefix)
    return compat.generate_routes()
