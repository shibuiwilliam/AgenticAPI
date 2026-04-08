"""Main AgenticApp application class.

Provides the top-level AgenticApp that serves as an ASGI application,
analogous to FastAPI's FastAPI class. Integrates intent parsing,
code generation, harness execution, and session management.
"""

from __future__ import annotations

import inspect
import json
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from agenticapi.exceptions import (
    EXCEPTION_STATUS_MAP,
    AgenticAPIError,
    ApprovalRequired,
    AuthenticationError,
    IntentParseError,
    PolicyViolation,
)
from agenticapi.interface.endpoint import AgentEndpointDef
from agenticapi.interface.intent import Intent, IntentParser, IntentScope
from agenticapi.interface.response import AgentResponse, FileResult, ResponseFormatter
from agenticapi.interface.session import SessionManager
from agenticapi.interface.tasks import AgentTasks
from agenticapi.interface.upload import UploadedFiles, UploadFile
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
    from agenticapi.security import Authenticator, AuthUser

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
        middleware: list[Middleware] | None = None,
        auth: Authenticator | None = None,
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
            middleware: Optional list of Starlette Middleware instances to apply.
                Analogous to FastAPI's middleware parameter.
            auth: Optional default Authenticator applied to all endpoints.
                Per-endpoint ``auth=`` overrides this. Set to None to disable auth.
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
        self._extra_routes: list[BaseRoute] = []
        self._auth: Authenticator | None = auth
        self._middleware: list[Middleware] = list(middleware) if middleware else []
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
        enable_mcp: bool = False,
        auth: Authenticator | None = None,
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
            enable_mcp: Whether to expose this endpoint as an MCP tool.
            auth: Optional Authenticator for this endpoint. Overrides app-level auth.

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
                enable_mcp=enable_mcp,
                auth=auth,
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
                enable_mcp=endpoint_def.enable_mcp,
                auth=endpoint_def.auth,
            )
        self._starlette_app = None

    def register_ops_agent(self, agent: OpsAgent) -> None:
        """Register an ops agent for lifecycle management.

        Args:
            agent: An OpsAgent instance to register.
        """
        self._ops_agents.append(agent)

    def add_routes(self, routes: list[BaseRoute]) -> None:
        """Add extra Starlette routes or mounts (e.g. REST compat, MCP server).

        Args:
            routes: List of Starlette BaseRoute objects (Route or Mount) to include.
        """
        self._extra_routes.extend(routes)
        self._starlette_app = None  # Force rebuild

    def add_middleware(self, cls: Any, **kwargs: Any) -> None:
        """Add Starlette middleware to the application.

        Analogous to FastAPI's ``app.add_middleware()``. Middleware wraps the
        entire ASGI application and is called on every request/response.

        Use this for cross-cutting HTTP concerns like CORS, compression,
        authentication headers, or request timing. For agent-specific request
        context enrichment, use ``DynamicPipeline`` instead.

        Args:
            cls: A Starlette middleware class (e.g. ``CORSMiddleware``).
            **kwargs: Keyword arguments passed to the middleware constructor.

        Example:
            from starlette.middleware.cors import CORSMiddleware

            app.add_middleware(
                CORSMiddleware,
                allow_origins=["http://localhost:3000"],
                allow_methods=["*"],
                allow_headers=["*"],
            )
        """
        self._middleware.append(Middleware(cls, **kwargs))
        self._starlette_app = None  # Force rebuild

    async def process_intent(
        self,
        raw_request: str,
        *,
        endpoint_name: str | None = None,
        session_id: str | None = None,
        auth_user: AuthUser | None = None,
        files: dict[str, UploadFile] | None = None,
    ) -> AgentResponse | Response:
        """Process a natural language request programmatically.

        This is the main programmatic API. Runs the full pipeline:
        intent parsing, scope checking, code generation (if LLM available),
        harness execution, and response construction.

        If no LLM is provided, calls the registered handler directly
        with the parsed intent and context.

        When the handler returns a Starlette ``Response`` (e.g. ``FileResponse``,
        ``StreamingResponse``) or a ``FileResult``, the response is returned
        directly without JSON wrapping.

        Args:
            raw_request: The natural language request string.
            endpoint_name: Optional endpoint name to target. If None,
                uses the first registered endpoint.
            session_id: Optional session ID for multi-turn conversations.
            auth_user: Optional authenticated user from the security layer.
            files: Optional uploaded files from multipart form data.

        Returns:
            An AgentResponse (for JSON results) or a Starlette Response (for files).
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
        metadata: dict[str, Any] = {}
        if auth_user is not None:
            metadata["auth_user"] = auth_user
        if files:
            metadata["files"] = files
        context = AgentContext(
            trace_id=trace_id,
            endpoint_name=endpoint_def.name,
            session_id=session.session_id,
            user_id=auth_user.user_id if auth_user else None,
            metadata=metadata,
        )

        # Execute
        response, tasks = await self._execute_intent(intent, context, endpoint_def)

        # Update session (skip for raw Response — no structured result to summarize)
        if isinstance(response, AgentResponse):
            result_summary = str(response.result)[:200] if response.result is not None else response.status
            session.add_turn(intent_raw=raw_request, response_summary=result_summary)
        else:
            session.add_turn(intent_raw=raw_request, response_summary="[file response]")
        await self._session_manager.update(session)

        # Execute background tasks (after response is built but before return)
        if tasks is not None and tasks.pending_count > 0:
            await tasks.execute()

        return response

    async def _execute_intent(
        self,
        intent: Intent,
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> tuple[AgentResponse | Response, AgentTasks | None]:
        """Execute the intent through the appropriate pipeline.

        If an LLM and harness are available, uses code generation and
        harness execution. Otherwise, calls the handler directly.

        Args:
            intent: The parsed intent.
            context: The agent execution context.
            endpoint_def: The endpoint definition.

        Returns:
            Tuple of (AgentResponse or Response, AgentTasks or None).
            A raw Starlette Response is returned when the handler produces
            a file download (FileResult, FileResponse, StreamingResponse).
        """
        if self._llm is not None and self._harness is not None:
            return await self._execute_with_harness(intent, context, endpoint_def), None

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
    ) -> tuple[AgentResponse | Response, AgentTasks | None]:
        """Execute by calling the handler function directly.

        Used when no LLM is configured, for simple handler-based usage.
        Supports automatic parameter injection for ``AgentTasks`` and
        ``UploadedFiles``.

        If the handler returns a Starlette ``Response`` or a ``FileResult``,
        it is passed through directly (no JSON wrapping).

        Args:
            intent: The parsed intent.
            context: The agent execution context.
            endpoint_def: The endpoint definition.

        Returns:
            Tuple of (AgentResponse or Response, AgentTasks or None).
        """
        # Inject optional handler parameters (AgentTasks, UploadedFiles)
        tasks: AgentTasks | None = None
        sig = inspect.signature(endpoint_def.handler)
        handler_kwargs: dict[str, Any] = {}
        for param_name, param in sig.parameters.items():
            if param.annotation is AgentTasks or (
                isinstance(param.annotation, str) and "AgentTasks" in param.annotation
            ):
                tasks = AgentTasks()
                handler_kwargs[param_name] = tasks
            elif param.annotation is UploadedFiles or (
                isinstance(param.annotation, str) and "UploadedFiles" in param.annotation
            ):
                handler_kwargs[param_name] = context.metadata.get("files", {})

        try:
            if handler_kwargs:
                result = endpoint_def.handler(intent, context, **handler_kwargs)
            else:
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
            ), tasks

        # File response passthrough: bypass AgentResponse wrapping
        if isinstance(result, Response):
            return result, tasks
        if isinstance(result, FileResult):
            return result.to_response(), tasks

        return AgentResponse(
            result=result,
            status="completed",
            confidence=intent.confidence,
        ), tasks

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
        routes: list[BaseRoute] = []

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

        return Starlette(
            routes=routes,
            lifespan=lifespan,
            middleware=self._middleware or None,
        )

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

        async def handler(request: Request) -> Response:
            # --- Authentication (before body parsing) ---
            auth_user: AuthUser | None = None
            effective_auth = endpoint_def.auth or self._auth
            if effective_auth is not None:
                try:
                    credentials = await effective_auth.scheme(request)
                    if credentials is not None:
                        auth_user = await effective_auth.verify(credentials)
                        if auth_user is None:
                            raise AuthenticationError("Invalid credentials")
                except AuthenticationError as exc:
                    status_code = EXCEPTION_STATUS_MAP.get(type(exc), 401)
                    return JSONResponse(
                        {"error": str(exc), "status": "error"},
                        status_code=status_code,
                    )
                except Exception as exc:
                    logger.error("auth_failed", endpoint_name=name, error=str(exc))
                    return JSONResponse(
                        {"error": f"Authentication error: {exc}", "status": "error"},
                        status_code=401,
                    )

            # --- Parse request body (JSON or multipart) ---
            uploaded_files: dict[str, UploadFile] | None = None
            content_type = request.headers.get("content-type", "")

            if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
                try:
                    form = await request.form()
                    raw_intent = str(form.get("intent", ""))
                    raw_session_id = form.get("session_id")
                    session_id = str(raw_session_id) if isinstance(raw_session_id, str) and raw_session_id else None

                    # Collect uploaded files (50 MB per-file limit)
                    max_file_size = 50 * 1024 * 1024
                    uploaded_files = {}
                    for key, value in form.multi_items():
                        if hasattr(value, "read"):
                            file_content = await value.read()
                            if len(file_content) > max_file_size:
                                return JSONResponse(
                                    {
                                        "error": f"File '{key}' exceeds maximum size ({len(file_content)} bytes, "
                                        f"limit {max_file_size} bytes)",
                                        "status": "error",
                                    },
                                    status_code=413,
                                )
                            uploaded_files[key] = UploadFile(
                                filename=getattr(value, "filename", key) or key,
                                content_type=getattr(value, "content_type", "application/octet-stream")
                                or "application/octet-stream",
                                content=file_content,
                                size=len(file_content),
                            )
                except Exception as exc:
                    logger.error("multipart_parse_failed", error=str(exc), error_type=type(exc).__name__)
                    return JSONResponse(
                        {"error": "Failed to parse multipart form data", "status": "error"},
                        status_code=400,
                    )
            else:
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
                    auth_user=auth_user,
                    files=uploaded_files,
                )
                # File response passthrough: return directly without JSON wrapping
                if isinstance(response, Response):
                    return response
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
