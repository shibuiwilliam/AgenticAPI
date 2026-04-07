"""Main AgenticApp application class.

Provides the top-level AgenticApp that serves as an ASGI application,
analogous to FastAPI's FastAPI class. Integrates intent parsing,
code generation, harness execution, and session management.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from agenticapi.exceptions import (
    EXCEPTION_STATUS_MAP,
    AgenticAPIError,
    ApprovalRequired,
    IntentParseError,
    PolicyViolation,
)
from agenticapi.interface.endpoint import AgentEndpointDef
from agenticapi.interface.intent import Intent, IntentParser, IntentScope
from agenticapi.interface.response import AgentResponse, ResponseFormatter
from agenticapi.interface.session import SessionManager
from agenticapi.runtime.context import AgentContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

    from agenticapi.harness.engine import HarnessEngine
    from agenticapi.ops.base import OpsAgent
    from agenticapi.routing import AgentRouter
    from agenticapi.runtime.code_generator import CodeGenerator
    from agenticapi.runtime.llm.base import LLMBackend
    from agenticapi.runtime.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


class AgenticApp:
    """Main AgenticAPI application. ASGI-compatible, runs with uvicorn.

    Integrates all layers of AgenticAPI: intent parsing, code generation,
    harness-controlled execution, and session management. Builds on
    Starlette for HTTP/ASGI handling.

    Example:
        app = AgenticApp(title="My Service")

        @app.agent_endpoint(name="orders", autonomy_level="supervised")
        async def order_agent(intent, context):
            return {"order_count": 42}

        # Run with: uvicorn myapp:app --host 0.0.0.0 --port 8000
    """

    def __init__(
        self,
        *,
        title: str = "AgenticAPI",
        version: str = "0.1.0",
        description: str = "",
        harness: HarnessEngine | None = None,
        llm: LLMBackend | None = None,
        tools: ToolRegistry | None = None,
        docs_url: str | None = "/docs",
        redoc_url: str | None = "/redoc",
        openapi_url: str | None = "/openapi.json",
    ) -> None:
        """Initialize the application.

        Args:
            title: Application title for documentation.
            version: Application version string.
            description: Optional description shown in OpenAPI docs.
            harness: Optional HarnessEngine for policy evaluation and sandbox execution.
            llm: Optional LLM backend for intent parsing and code generation.
            tools: Optional ToolRegistry defining tools available to generated code.
            docs_url: URL path for Swagger UI. Set to None to disable.
            redoc_url: URL path for ReDoc UI. Set to None to disable.
            openapi_url: URL path for OpenAPI JSON schema. Set to None to disable all docs.
        """
        self.title = title
        self.version = version
        self.description = description
        self._endpoints: dict[str, AgentEndpointDef] = {}
        self._harness = harness
        self._llm = llm
        self._tools = tools
        self._ops_agents: list[OpsAgent] = []
        self._starlette_app: Starlette | None = None
        self._session_manager = SessionManager()
        self._intent_parser = IntentParser(llm=llm)
        self._response_formatter = ResponseFormatter()
        self._code_generator: CodeGenerator | None = None
        self._extra_routes: list[Route] = []
        self._docs_url = docs_url
        self._redoc_url = redoc_url
        self._openapi_url = openapi_url

    @property
    def harness(self) -> HarnessEngine | None:
        """The harness engine, if configured."""
        return self._harness

    @property
    def session_manager(self) -> SessionManager:
        """The session manager."""
        return self._session_manager

    def agent_endpoint(
        self,
        name: str,
        *,
        description: str = "",
        intent_scope: IntentScope | None = None,
        autonomy_level: str = "supervised",
        policies: list[Any] | None = None,
        approval: Any | None = None,
        sandbox: Any | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register an agent endpoint.

        Decorator for registering handler functions as agent endpoints.
        Analogous to FastAPI's @app.get() / @app.post().

        Args:
            name: Unique name for the endpoint.
            description: Human-readable description.
            intent_scope: Optional scope constraints for allowed intents.
            autonomy_level: Agent autonomy level ("auto", "supervised", "manual").
            policies: List of policies to enforce on this endpoint.
            approval: Optional approval workflow configuration.
            sandbox: Optional sandbox configuration override.

        Returns:
            A decorator that registers the handler function.
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._endpoints[name] = AgentEndpointDef(
                name=name,
                handler=func,
                description=description,
                intent_scope=intent_scope,
                autonomy_level=autonomy_level,
                policies=policies or [],
                approval=approval,
                sandbox=sandbox,
            )
            # Force Starlette app rebuild on next request
            self._starlette_app = None
            return func

        return decorator

    def include_router(self, router: AgentRouter, *, prefix: str = "") -> None:
        """Include all endpoints from a router.

        Analogous to FastAPI's include_router.

        Args:
            router: The AgentRouter to include.
            prefix: Additional prefix to prepend to endpoint names.
        """
        for name, endpoint_def in router.endpoints.items():
            full_name = f"{prefix}.{name}" if prefix else name
            self._endpoints[full_name] = AgentEndpointDef(
                name=full_name,
                handler=endpoint_def.handler,
                description=endpoint_def.description,
                intent_scope=endpoint_def.intent_scope,
                autonomy_level=endpoint_def.autonomy_level,
                policies=endpoint_def.policies,
                approval=endpoint_def.approval,
                sandbox=endpoint_def.sandbox,
            )
        self._starlette_app = None

    def register_ops_agent(self, agent: OpsAgent) -> None:
        """Register an ops agent for lifecycle management.

        Args:
            agent: An OpsAgent instance to register.
        """
        self._ops_agents.append(agent)

    def add_routes(self, routes: list[Route]) -> None:
        """Add extra Starlette routes (e.g. REST compat routes).

        Args:
            routes: List of Starlette Route objects to include.
        """
        self._extra_routes.extend(routes)
        self._starlette_app = None  # Force rebuild

    async def process_intent(
        self,
        raw_request: str,
        *,
        endpoint_name: str | None = None,
        session_id: str | None = None,
    ) -> AgentResponse:
        """Process a natural language request programmatically.

        This is the main programmatic API. Runs the full pipeline:
        intent parsing, scope checking, code generation (if LLM available),
        harness execution, and response construction.

        If no LLM is provided, calls the registered handler directly
        with the parsed intent and context.

        Args:
            raw_request: The natural language request string.
            endpoint_name: Optional endpoint name to target. If None,
                uses the first registered endpoint.
            session_id: Optional session ID for multi-turn conversations.

        Returns:
            An AgentResponse with the result.
        """
        # Resolve endpoint
        endpoint_def = self._resolve_endpoint(endpoint_name)

        # Get or create session
        session = await self._session_manager.get_or_create(session_id)

        # Parse intent
        intent = await self._intent_parser.parse(
            raw_request,
            session_context=session.context,
        )

        # Check intent scope
        if endpoint_def.intent_scope is not None and not endpoint_def.intent_scope.matches(intent):
            raise PolicyViolation(
                policy="intent_scope",
                violation=f"Intent '{intent.domain}.{intent.action}' is not allowed by endpoint scope",
            )

        # Build context
        trace_id = uuid.uuid4().hex
        context = AgentContext(
            trace_id=trace_id,
            endpoint_name=endpoint_def.name,
            session_id=session.session_id,
        )

        # Execute
        response = await self._execute_intent(intent, context, endpoint_def)

        # Update session
        result_summary = str(response.result)[:200] if response.result is not None else response.status
        session.add_turn(intent_raw=raw_request, response_summary=result_summary)
        await self._session_manager.update(session)

        return response

    async def _execute_intent(
        self,
        intent: Intent,
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> AgentResponse:
        """Execute the intent through the appropriate pipeline.

        If an LLM and harness are available, uses code generation and
        harness execution. Otherwise, calls the handler directly.

        Args:
            intent: The parsed intent.
            context: The agent execution context.
            endpoint_def: The endpoint definition.

        Returns:
            An AgentResponse.
        """
        if self._llm is not None and self._harness is not None:
            return await self._execute_with_harness(intent, context, endpoint_def)

        # Direct handler invocation (no LLM/harness)
        return await self._execute_handler_directly(intent, context, endpoint_def)

    async def _execute_with_harness(
        self,
        intent: Intent,
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> AgentResponse:
        """Execute intent through code generation and harness pipeline.

        Args:
            intent: The parsed intent.
            context: The agent execution context.
            endpoint_def: The endpoint definition.

        Returns:
            An AgentResponse.
        """
        # Lazy-init code generator
        if self._code_generator is None:
            from agenticapi.runtime.code_generator import CodeGenerator

            self._code_generator = CodeGenerator(llm=self._llm, tools=self._tools)  # type: ignore[arg-type]

        assert self._harness is not None

        # Pre-fetch data from tools (shared between code gen prompt and sandbox)
        sandbox_data: dict[str, object] = {}
        if self._tools is not None:
            for tool_def in self._tools.get_definitions():
                tool = self._tools.get(tool_def.name)
                try:
                    tool_result = await tool.invoke(query=f"SELECT * FROM {tool_def.name}")
                    sandbox_data[tool_def.name] = tool_result
                except Exception:
                    sandbox_data[tool_def.name] = []

        # Generate code (with data sample in prompt so LLM knows the schema)
        generated = await self._code_generator.generate(
            intent_raw=intent.raw,
            intent_action=intent.action.value,
            intent_domain=intent.domain,
            intent_parameters=intent.parameters,
            context=context,
            sandbox_data=sandbox_data if sandbox_data else None,
        )

        # Execute through harness
        result = await self._harness.execute(
            intent_raw=intent.raw,
            intent_action=intent.action.value,
            intent_domain=intent.domain,
            generated_code=generated.code,
            reasoning=generated.reasoning,
            endpoint_name=endpoint_def.name,
            context=context,
            sandbox_data=sandbox_data if sandbox_data else None,
        )

        return AgentResponse(
            result=result.output,
            status="completed",
            generated_code=result.generated_code,
            reasoning=result.reasoning,
            confidence=generated.confidence,
            execution_trace_id=result.trace.trace_id if result.trace else None,
        )

    async def _execute_handler_directly(
        self,
        intent: Intent,
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> AgentResponse:
        """Execute by calling the handler function directly.

        Used when no LLM is configured, for simple handler-based usage.

        Args:
            intent: The parsed intent.
            context: The agent execution context.
            endpoint_def: The endpoint definition.

        Returns:
            An AgentResponse wrapping the handler's return value.
        """
        try:
            result = endpoint_def.handler(intent, context)
            # Support both sync and async handlers
            if hasattr(result, "__await__"):
                result = await result
        except AgenticAPIError:
            raise
        except Exception as exc:
            logger.error(
                "handler_execution_failed",
                endpoint_name=endpoint_def.name,
                error=str(exc),
            )
            return AgentResponse(
                result=None,
                status="error",
                error=str(exc),
            )

        return AgentResponse(
            result=result,
            status="completed",
            confidence=intent.confidence,
        )

    def _resolve_endpoint(self, endpoint_name: str | None) -> AgentEndpointDef:
        """Resolve an endpoint by name.

        Args:
            endpoint_name: The endpoint name, or None for the first registered.

        Returns:
            The matching AgentEndpointDef.

        Raises:
            IntentParseError: If no matching endpoint is found.
        """
        if not self._endpoints:
            raise IntentParseError("No agent endpoints registered")

        if endpoint_name is None:
            return next(iter(self._endpoints.values()))

        endpoint = self._endpoints.get(endpoint_name)
        if endpoint is None:
            available = list(self._endpoints.keys())
            raise IntentParseError(f"Endpoint '{endpoint_name}' not found. Available: {available}")
        return endpoint

    def _build_starlette(self) -> Starlette:
        """Build the internal Starlette application with routes.

        Returns:
            A configured Starlette application.
        """
        routes: list[Route] = []

        for name, endpoint_def in self._endpoints.items():
            handler = self._create_endpoint_handler(name, endpoint_def)
            routes.append(Route(f"/agent/{name}", handler, methods=["POST"]))

        routes.extend(self._extra_routes)
        routes.append(Route("/health", self._health_handler, methods=["GET"]))
        routes.append(Route("/capabilities", self._capabilities_handler, methods=["GET"]))

        # OpenAPI / Swagger / ReDoc
        if self._openapi_url is not None:
            from agenticapi.openapi import build_openapi_routes

            routes.extend(
                build_openapi_routes(
                    title=self.title,
                    version=self.version,
                    endpoints=self._endpoints,
                    description=self.description,
                    openapi_url=self._openapi_url,
                    docs_url=self._docs_url or "/docs",
                    redoc_url=self._redoc_url or "/redoc",
                )
            )

        @asynccontextmanager
        async def lifespan(app: Starlette):  # type: ignore[no-untyped-def]
            await self._on_startup()
            yield
            await self._on_shutdown()

        return Starlette(routes=routes, lifespan=lifespan)

    def _create_endpoint_handler(
        self,
        name: str,
        endpoint_def: AgentEndpointDef,
    ) -> Callable[..., Any]:
        """Create a Starlette request handler for an agent endpoint.

        The handler:
        1. Parses JSON body (expects {"intent": "...", "session_id": "...", "context": {...}})
        2. Parses intent using IntentParser
        3. Checks IntentScope
        4. Generates code using CodeGenerator (if LLM available)
        5. Executes through HarnessEngine
        6. Returns JSON response

        Args:
            name: The endpoint name.
            endpoint_def: The endpoint definition.

        Returns:
            An async Starlette handler function.
        """

        async def handler(request: Request) -> JSONResponse:
            try:
                body = await request.json()
            except json.JSONDecodeError:
                return JSONResponse(
                    {"error": "Invalid JSON body", "status": "error"},
                    status_code=400,
                )
            except Exception as exc:
                logger.error("request_body_read_failed", error=str(exc))
                return JSONResponse(
                    {"error": "Failed to read request body", "status": "error"},
                    status_code=500,
                )

            raw_intent = body.get("intent", "")
            session_id = body.get("session_id")

            if not raw_intent:
                return JSONResponse(
                    {"error": "Missing 'intent' field in request body", "status": "error"},
                    status_code=400,
                )

            try:
                response = await self.process_intent(
                    raw_intent,
                    endpoint_name=name,
                    session_id=session_id,
                )
                return JSONResponse(
                    self._response_formatter.format_json(response),
                    status_code=200,
                )
            except ApprovalRequired as exc:
                approval_info = None
                if exc.request_id:
                    approval_info = {
                        "request_id": exc.request_id,
                        "approvers": exc.approvers,
                    }
                response = AgentResponse(
                    result=None,
                    status="pending_approval",
                    error=str(exc),
                    approval_request=approval_info,
                )
                return JSONResponse(
                    self._response_formatter.format_json(response),
                    status_code=EXCEPTION_STATUS_MAP.get(type(exc), 500),
                )
            except AgenticAPIError as exc:
                status_code = EXCEPTION_STATUS_MAP.get(type(exc), 500)
                response = AgentResponse(result=None, status="error", error=str(exc))
                return JSONResponse(
                    self._response_formatter.format_json(response),
                    status_code=status_code,
                )
            except Exception as exc:
                logger.error(
                    "endpoint_unhandled_error",
                    endpoint_name=name,
                    error=str(exc),
                )
                response = AgentResponse(result=None, status="error", error="Internal server error")
                return JSONResponse(
                    self._response_formatter.format_json(response),
                    status_code=500,
                )

        return handler

    async def _health_handler(self, request: Request) -> JSONResponse:
        """Health check endpoint handler.

        Args:
            request: The incoming Starlette request.

        Returns:
            JSON response with status and version.
        """
        ops_health: list[dict[str, object]] = []
        for agent in self._ops_agents:
            try:
                health = await agent.check_health()
                ops_health.append(
                    {
                        "name": agent.name,
                        "healthy": health.healthy,
                        "message": health.message,
                    }
                )
            except Exception as exc:
                ops_health.append({"name": agent.name, "healthy": False, "message": str(exc)})

        result: dict[str, object] = {
            "status": "ok",
            "version": self.version,
            "endpoints": list(self._endpoints.keys()),
        }
        if ops_health:
            result["ops_agents"] = ops_health
        return JSONResponse(result)

    async def _capabilities_handler(self, request: Request) -> JSONResponse:
        """Capability discovery endpoint for external agents.

        Returns structured metadata about all registered endpoints,
        including descriptions, intent scopes, and autonomy levels.

        Args:
            request: The incoming Starlette request.

        Returns:
            JSON response with endpoint capabilities.
        """
        capabilities: list[dict[str, object]] = []
        for name, ep in self._endpoints.items():
            cap: dict[str, object] = {
                "name": name,
                "description": ep.description,
                "autonomy_level": ep.autonomy_level,
            }
            if ep.intent_scope is not None:
                cap["intent_scope"] = {
                    "allowed_intents": ep.intent_scope.allowed_intents,
                    "denied_intents": ep.intent_scope.denied_intents,
                }
            capabilities.append(cap)

        return JSONResponse(
            {
                "title": self.title,
                "version": self.version,
                "endpoints": capabilities,
            }
        )

    async def _on_startup(self) -> None:
        """Startup hook for initializing ops agents."""
        for agent in self._ops_agents:
            await agent.start()
        logger.info(
            "agenticapi_started",
            title=self.title,
            version=self.version,
            endpoint_count=len(self._endpoints),
        )

    async def _on_shutdown(self) -> None:
        """Shutdown hook for stopping ops agents."""
        for agent in self._ops_agents:
            try:
                await agent.stop()
            except Exception as exc:
                logger.error("ops_agent_stop_failed", agent_name=agent.name, error=str(exc))
        logger.info("agenticapi_shutdown")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """ASGI interface.

        Delegates to the internal Starlette application.

        Args:
            scope: ASGI scope dict.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if self._starlette_app is None:
            self._starlette_app = self._build_starlette()
        await self._starlette_app(scope, receive, send)
