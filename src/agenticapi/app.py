"""Main AgenticApp application class.

Provides the top-level AgenticApp that serves as an ASGI application,
analogous to FastAPI's FastAPI class. Integrates intent parsing,
code generation, harness execution, and session management.
"""

from __future__ import annotations

import json
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route

from agenticapi.dependencies import invoke_handler, scan_handler, solve
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
from agenticapi.interface.response import AgentResponse, FileResult, HTMLResult, PlainTextResult, ResponseFormatter
from agenticapi.interface.session import SessionManager
from agenticapi.interface.upload import UploadFile
from agenticapi.observability import (
    AgenticAPIAttributes,
    SpanNames,
    extract_context_from_headers,
    get_tracer,
    should_record_prompt_bodies,
)
from agenticapi.runtime.context import AgentContext

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic import BaseModel
    from starlette.requests import Request

    from agenticapi.dependencies.depends import Dependency
    from agenticapi.harness.engine import HarnessEngine
    from agenticapi.harness.policy.autonomy_policy import AutonomyPolicy
    from agenticapi.interface.tasks import AgentTasks
    from agenticapi.ops.base import OpsAgent
    from agenticapi.routing import AgentRouter
    from agenticapi.runtime.code_cache import CodeCache
    from agenticapi.runtime.code_generator import CodeGenerator
    from agenticapi.runtime.llm.base import LLMBackend
    from agenticapi.runtime.loop import LoopConfig
    from agenticapi.runtime.memory.base import MemoryStore
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
        memory: MemoryStore | None = None,
        code_cache: CodeCache | None = None,
        middleware: list[Middleware] | None = None,
        auth: Authenticator | None = None,
        docs_url: str | None = "/docs",
        redoc_url: str | None = "/redoc",
        openapi_url: str | None = "/openapi.json",
        metrics_url: str | None = None,
        playground_url: str | None = None,
        trace_url: str | None = None,
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
            metrics_url: URL path for Prometheus metrics exposition.
                Set to ``None`` (default) to disable. When set, the
                framework registers a ``GET {metrics_url}`` route that
                serves the canonical AgenticAPI metric set
                (request count, duration histogram, policy denials,
                LLM tokens, LLM cost, sandbox violations,
                tool calls, budget blocks). Requires
                ``opentelemetry-api`` + ``opentelemetry-sdk`` (and
                optionally ``opentelemetry-exporter-prometheus``); if
                missing, the endpoint returns an empty body and a
                warning is logged at app start.
        """
        self.title = title
        self.version = version
        self.description = description
        self._endpoints: dict[str, AgentEndpointDef] = {}
        self._harness = harness
        self._llm = llm
        self._tools = tools
        # Phase C1: optional memory store attached to every
        # AgentContext the framework builds. Handlers read + write
        # via ``context.memory``; when ``None`` the attribute is
        # ``None`` and handlers that don't use memory see no change
        # from the pre-C1 behaviour.
        self._memory: MemoryStore | None = memory
        # Phase C5: optional approved-code cache. When set, a cache
        # hit on the LLM path skips the code-generation call and
        # reuses previously-approved code. When ``None``, the
        # framework still runs the legacy path — zero behaviour
        # change for apps that don't opt in.
        self._code_cache: CodeCache | None = code_cache
        self._ops_agents: list[OpsAgent] = []
        self._starlette_app: Starlette | None = None
        self._session_manager = SessionManager()
        self._intent_parser = IntentParser(llm=llm)
        self._response_formatter = ResponseFormatter()
        self._code_generator: CodeGenerator | None = None
        self._extra_routes: list[BaseRoute] = []
        self._lifespan_managers: list[Callable[[], Any]] = []
        self._auth: Authenticator | None = auth
        self._middleware: list[Middleware] = list(middleware) if middleware else []
        self._docs_url = docs_url
        self._redoc_url = redoc_url
        self._openapi_url = openapi_url
        self._metrics_url = metrics_url

        # Initialise metrics on first construction so the recording
        # helpers in agenticapi.observability.metrics actually wire
        # to a meter. Safe to call repeatedly — re-init is a no-op.
        if metrics_url is not None:
            from agenticapi.observability import configure_metrics

            configure_metrics(service_name=title)
        # Public mapping that mirrors FastAPI's ``app.dependency_overrides``.
        # Tests assign here to substitute a dependency callable with a
        # mock implementation; the assignment is consulted by the
        # solver on every request.
        self.dependency_overrides: dict[Callable[..., Any], Callable[..., Any]] = {}

        # Phase F5: in-process registry of pending approval handles.
        # The streaming endpoint factory creates handles via this
        # registry and the resume route resolves them. Single-host
        # only — multi-host deployments will swap this for a
        # Redis-backed registry in Phase F7.
        from agenticapi.interface.approval_registry import ApprovalRegistry
        from agenticapi.interface.stream_store import InMemoryStreamStore

        self._approval_registry = ApprovalRegistry()
        # Phase F7: in-process stream event log for reconnect/resume.
        # Every emit on an AgentStream is mirrored into this store,
        # and the GET /agent/{name}/stream/{stream_id} route tails
        # from here. Multi-host deployments swap the implementation
        # via the public setter below.
        self._stream_store: Any = InMemoryStreamStore()

        # Playground: self-hosted agent debugger UI.
        self._playground_routes: list[BaseRoute] = []
        self._playground_url = playground_url
        if playground_url is not None:
            from agenticapi.playground import mount_playground

            mount_playground(self, playground_url)

        # Trace inspector: self-hosted trace inspection UI.
        self._trace_inspector_routes: list[BaseRoute] = []
        self._trace_url = trace_url
        if trace_url is not None:
            from agenticapi.trace_inspector import mount_trace_inspector

            mount_trace_inspector(self, trace_url)

    @property
    def _dependency_overrides(self) -> dict[Callable[..., Any], Callable[..., Any]]:
        """Internal accessor used by the solver. Indirected for type narrowing."""
        return self.dependency_overrides

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
        autonomy: AutonomyPolicy | None = None,
        policies: list[Any] | None = None,
        approval: Any | None = None,
        sandbox: Any | None = None,
        enable_mcp: bool = False,
        auth: Authenticator | None = None,
        response_model: type[BaseModel] | None = None,
        dependencies: list[Dependency] | None = None,
        streaming: str | None = None,
        loop_config: LoopConfig | None = None,
        workflow: Any | None = None,
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
            response_model: Optional Pydantic model the handler return
                value is validated against. When set, the model schema
                is also published in OpenAPI for this endpoint, giving
                the same FastAPI-style schema-driven docs developers
                expect.
            dependencies: Optional list of route-level dependencies
                that run before the handler for side effects only.
                Their return values are discarded; exceptions
                propagate normally so an auth check that raises
                ``AuthenticationError`` short-circuits the request.
                Mirrors FastAPI's ``dependencies=`` parameter.
            workflow: Optional :class:`AgentWorkflow` for multi-step
                workflow execution. When set, the intent is fed into
                the workflow engine instead of the handler. The
                handler serves as a fallback for manual-mode endpoints.

        Returns:
            A decorator that registers the handler function.
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            # Effective legacy ``autonomy_level`` string: when an
            # AutonomyPolicy is supplied, its ``start`` takes over as
            # the baseline so approval decisions and audit attributes
            # stay consistent.
            effective_autonomy_level = autonomy.start.value if autonomy is not None else autonomy_level
            self._endpoints[name] = AgentEndpointDef(
                name=name,
                handler=func,
                description=description,
                intent_scope=intent_scope,
                autonomy_level=effective_autonomy_level,
                autonomy=autonomy,
                policies=policies or [],
                approval=approval,
                sandbox=sandbox,
                enable_mcp=enable_mcp,
                auth=auth,
                response_model=response_model,
                injection_plan=scan_handler(func),
                dependencies=list(dependencies or []),
                streaming=streaming,
                loop_config=loop_config,
                workflow=workflow,
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
                autonomy=endpoint_def.autonomy,
                policies=endpoint_def.policies,
                approval=endpoint_def.approval,
                sandbox=endpoint_def.sandbox,
                enable_mcp=endpoint_def.enable_mcp,
                auth=endpoint_def.auth,
                response_model=endpoint_def.response_model,
                injection_plan=endpoint_def.injection_plan or scan_handler(endpoint_def.handler),
                dependencies=list(endpoint_def.dependencies),
                streaming=endpoint_def.streaming,
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

    def add_lifespan(self, manager_factory: Callable[[], Any]) -> None:
        """Register an async context manager to be entered/exited with the app lifespan.

        Required for mounted ASGI sub-apps that have their own lifespan
        (e.g. FastMCP's streamable HTTP server). Starlette does not propagate
        lifespan events to mounted apps automatically, so they must be
        registered explicitly.

        Args:
            manager_factory: A zero-arg callable returning an async context
                manager. Called once at app startup; the result is entered
                via ``AsyncExitStack``. Failures during entry abort startup;
                exit always runs at shutdown.

        Example:
            mcp_app = mcp.streamable_http_app()
            app.add_lifespan(lambda: mcp_app.router.lifespan_context(mcp_app))
        """
        self._lifespan_managers.append(manager_factory)
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
        _scope: dict[str, Any] | None = None,
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

        # Phase A2: track wall-clock duration so we can record the
        # request_duration_seconds histogram on completion.
        import time as _time

        from agenticapi.observability import record_request

        request_started = _time.monotonic()
        request_status = "completed"

        # Phase A5: honour any incoming W3C ``traceparent`` header so
        # the framework's root span joins the upstream distributed
        # trace instead of starting a fresh one. Falls back to a new
        # trace context when no header is present or when OTel is
        # not installed (degrades to None, no-op tracer ignores it).
        upstream_headers = _headers_from_scope(_scope)
        upstream_context = extract_context_from_headers(upstream_headers)

        # Phase A1: open the root span for this request. The span
        # encloses every other span the framework opens (intent parse,
        # code generation, policy evaluation, sandbox execution,
        # audit recording) so an APM shows one tree per request.
        tracer = get_tracer()
        with tracer.start_as_current_span(
            SpanNames.AGENT_REQUEST.value,
            context=upstream_context,
        ) as request_span:
            request_span.set_attribute(AgenticAPIAttributes.ENDPOINT_NAME.value, endpoint_def.name)
            request_span.set_attribute(AgenticAPIAttributes.AUTONOMY_LEVEL.value, endpoint_def.autonomy_level)
            if auth_user is not None:
                request_span.set_attribute(AgenticAPIAttributes.USER_ID.value, auth_user.user_id)
            if should_record_prompt_bodies():
                request_span.set_attribute(AgenticAPIAttributes.INTENT_RAW.value, raw_request[:500])

            # Get or create session
            session = await self._session_manager.get_or_create(session_id)
            request_span.set_attribute(AgenticAPIAttributes.SESSION_ID.value, session.session_id)

            # Parse intent — when the handler declared ``Intent[T]``,
            # the scanner captured ``T`` on the cached injection plan
            # and we forward it to the parser so the LLM is constrained
            # to produce a payload matching the schema.
            plan = endpoint_def.injection_plan
            payload_schema = plan.intent_payload_schema if plan is not None else None
            with tracer.start_as_current_span(SpanNames.INTENT_PARSE.value) as parse_span:
                if payload_schema is not None:
                    parse_span.set_attribute(AgenticAPIAttributes.INTENT_PAYLOAD_SCHEMA.value, payload_schema.__name__)
                intent = await self._intent_parser.parse(
                    raw_request,
                    session_context=session.context,
                    schema=payload_schema,
                )
                parse_span.set_attribute(AgenticAPIAttributes.INTENT_ACTION.value, intent.action.value)
                parse_span.set_attribute(AgenticAPIAttributes.INTENT_DOMAIN.value, intent.domain)
                parse_span.set_attribute(AgenticAPIAttributes.INTENT_CONFIDENCE.value, intent.confidence)

            request_span.set_attribute(AgenticAPIAttributes.INTENT_ACTION.value, intent.action.value)
            request_span.set_attribute(AgenticAPIAttributes.INTENT_DOMAIN.value, intent.domain)

            # Check intent scope
            if endpoint_def.intent_scope is not None and not endpoint_def.intent_scope.matches(intent):
                request_span.add_event(
                    "intent_scope_denied",
                    attributes={
                        AgenticAPIAttributes.INTENT_ACTION.value: intent.action.value,
                        AgenticAPIAttributes.INTENT_DOMAIN.value: intent.domain,
                    },
                )
                raise PolicyViolation(
                    policy="intent_scope",
                    violation=f"Intent '{intent.domain}.{intent.action}' is not allowed by endpoint scope",
                )

            # Build context
            trace_id = uuid.uuid4().hex
            request_span.set_attribute(AgenticAPIAttributes.REQUEST_TRACE_ID.value, trace_id)
            metadata: dict[str, Any] = {}
            if auth_user is not None:
                metadata["auth_user"] = auth_user
            if files:
                metadata["files"] = files
            if _scope:
                metadata["scope"] = _scope
            context = AgentContext(
                trace_id=trace_id,
                endpoint_name=endpoint_def.name,
                session_id=session.session_id,
                user_id=auth_user.user_id if auth_user else None,
                metadata=metadata,
                memory=self._memory,
            )

            # Execute
            try:
                response, tasks = await self._execute_intent(intent, context, endpoint_def)
            except PolicyViolation:
                request_status = "policy_denied"
                raise
            except ApprovalRequired:
                request_status = "pending_approval"
                raise
            except AgenticAPIError:
                request_status = "error"
                raise

            # Update session (skip for raw Response — no structured result to summarize)
            if isinstance(response, AgentResponse):
                result_summary = str(response.result)[:200] if response.result is not None else response.status
                session.add_turn(intent_raw=raw_request, response_summary=result_summary)
                if response.status != "completed":
                    request_status = response.status
            else:
                session.add_turn(intent_raw=raw_request, response_summary="[file response]")
            await self._session_manager.update(session)

            # Execute background tasks (after response is built but before return)
            if tasks is not None and tasks.pending_count > 0:
                await tasks.execute()

            # A2: record request metric (counter + duration histogram)
            record_request(
                endpoint=endpoint_def.name,
                status=request_status,
                duration_seconds=_time.monotonic() - request_started,
            )

            return response

    async def _process_intent_streaming(
        self,
        raw_request: str,
        *,
        endpoint_def: AgentEndpointDef,
        session_id: str | None,
        auth_user: AuthUser | None,
        files: dict[str, UploadFile] | None,
        scope: dict[str, Any] | None,
    ) -> Response:
        """Streaming variant of :meth:`process_intent` (Phase F2).

        Builds an :class:`AgentStream`, resolves the handler's
        injection plan with the stream attached, and wraps the
        whole thing in the configured streaming transport
        (currently SSE only). Returns a Starlette ``StreamingResponse``.
        """
        from agenticapi.dependencies import invoke_handler, scan_handler, solve
        from agenticapi.interface.stream import AgentStream
        from agenticapi.interface.transports.ndjson import run_ndjson_response
        from agenticapi.interface.transports.sse import run_sse_response

        # Resolve the upstream traceparent (A5) so even streaming
        # requests join the upstream distributed trace.
        upstream_headers = _headers_from_scope(scope)
        upstream_context = extract_context_from_headers(upstream_headers)

        tracer = get_tracer()
        # We do NOT use ``with`` here because the span needs to stay
        # alive for the duration of the streaming response, which
        # outlives this method. We open it explicitly and rely on the
        # SSE transport to close it via ``stream.close()``.
        request_span = tracer.start_span(
            SpanNames.AGENT_REQUEST.value,
            attributes={
                AgenticAPIAttributes.ENDPOINT_NAME.value: endpoint_def.name,
                AgenticAPIAttributes.AUTONOMY_LEVEL.value: endpoint_def.autonomy_level,
            },
            context=upstream_context,
        )
        del request_span  # Held only for its side effect on the no-op tracer; real OTel span lives in the task

        # Get-or-create the session synchronously here so the
        # AgentStream can be tagged with the right session id.
        session = await self._session_manager.get_or_create(session_id)

        # Parse the intent now (not async-with-the-stream) — typed
        # intents (D4) work the same for streaming as for non-
        # streaming endpoints.
        plan = endpoint_def.injection_plan
        payload_schema = plan.intent_payload_schema if plan is not None else None
        intent = await self._intent_parser.parse(
            raw_request,
            session_context=session.context,
            schema=payload_schema,
        )

        # Intent scope (early bail-out — no stream needed).
        if endpoint_def.intent_scope is not None and not endpoint_def.intent_scope.matches(intent):
            raise PolicyViolation(
                policy="intent_scope",
                violation=(f"Intent '{intent.domain}.{intent.action}' is not allowed by endpoint scope"),
            )

        trace_id = uuid.uuid4().hex
        metadata: dict[str, Any] = {}
        if auth_user is not None:
            metadata["auth_user"] = auth_user
        if files:
            metadata["files"] = files
        if scope:
            metadata["scope"] = scope
        context = AgentContext(
            trace_id=trace_id,
            endpoint_name=endpoint_def.name,
            session_id=session.session_id,
            user_id=auth_user.user_id if auth_user else None,
            metadata=metadata,
            memory=self._memory,
        )

        # Phase F1: build the AgentStream and inject it via the solver.
        # Phase F5: hand the stream the approval-handle factory so
        # `request_approval` can route through the resume registry.
        # Phase F6: attach the endpoint's AutonomyPolicy (if any) so
        # `stream.report_signal(...)` drives live escalations through
        # the stream and the audit trail.
        stream = AgentStream(
            stream_id=trace_id,
            approval_handle_factory=self._approval_registry.create_handle_factory(trace_id),
            autonomy=endpoint_def.autonomy,
            stream_store=self._stream_store,
        )

        plan_to_use = endpoint_def.injection_plan or scan_handler(endpoint_def.handler)

        async def _run_handler() -> Any:
            resolved = await solve(
                plan_to_use,
                intent=intent,
                context=context,
                files=context.metadata.get("files"),
                htmx_scope=context.metadata.get("scope"),
                overrides=self._dependency_overrides,
                route_dependencies=endpoint_def.dependencies or None,
                agent_stream=stream,
            )
            return await invoke_handler(endpoint_def.handler, resolved)

        async def _record_audit(closed_stream: AgentStream) -> None:
            """Phase F8: record the streamed event log into the audit store.

            This runs as the SSE transport's ``on_complete`` callback,
            so by the time we read ``closed_stream.emitted_events``
            the terminal :class:`FinalEvent` (or
            :class:`ErrorEvent`) has already been appended.
            """
            if self._harness is None:
                # Drop pending approvals so the in-memory registry
                # doesn't grow forever even when there's no audit
                # recorder configured.
                self._approval_registry.discard(trace_id)
                return
            from agenticapi.harness.audit.trace import ExecutionTrace

            trace = ExecutionTrace(
                trace_id=trace_id,
                endpoint_name=endpoint_def.name,
                timestamp=datetime.now(tz=UTC),
                intent_raw=raw_request,
                intent_action=intent.action.value,
                generated_code="",
                reasoning=None,
                execution_duration_ms=0.0,
            )
            trace.stream_events = [event.model_dump(mode="json") for event in closed_stream.emitted_events]
            await self._harness.audit_recorder.record(trace)
            self._approval_registry.discard(trace_id)

        # Phase F2 / F3: dispatch based on configured transport.
        # The SSE and NDJSON transports share the same substrate
        # (stream consumer + handler-task factory + on_complete hook),
        # so the branch is a one-line table lookup.
        transport = (endpoint_def.streaming or "sse").lower()
        if transport == "ndjson":
            return await run_ndjson_response(
                stream=stream,
                handler_task_factory=_run_handler,
                on_complete=_record_audit,
            )
        if transport == "sse":
            return await run_sse_response(
                stream=stream,
                handler_task_factory=_run_handler,
                on_complete=_record_audit,
            )
        # Unknown transport — fall back to SSE and log so the
        # endpoint keeps working instead of 500'ing, but operators
        # see the misconfiguration in logs.
        logger.warning(
            "streaming_unknown_transport_falling_back_to_sse",
            endpoint=endpoint_def.name,
            requested_transport=endpoint_def.streaming,
        )
        return await run_sse_response(
            stream=stream,
            handler_task_factory=_run_handler,
            on_complete=_record_audit,
        )

    async def _execute_intent(
        self,
        intent: Intent[Any],
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
        # Pre-LLM input scanning: run text-scanning policies (B5/B6)
        # on the raw intent before any LLM call or handler execution.
        # Policies that don't override evaluate_intent_text default to
        # allow, so this is a no-op for CodePolicy, DataPolicy, etc.
        if self._harness is not None:
            self._harness.evaluate_intent_text(
                intent_text=intent.raw,
                intent_action=str(intent.action) if intent.action else "",
                intent_domain=intent.domain or "",
            )

        # Workflow execution: when a workflow is attached to the endpoint,
        # bypass the handler and run the workflow engine.
        if endpoint_def.workflow is not None:
            return await self._execute_workflow(intent, context, endpoint_def), None

        if self._llm is not None and self._harness is not None and endpoint_def.autonomy_level != "manual":
            return await self._execute_with_harness(intent, context, endpoint_def), None

        # Direct handler invocation: no LLM/harness, or autonomy_level="manual"
        return await self._execute_handler_directly(intent, context, endpoint_def)

    async def _execute_workflow(
        self,
        intent: Intent[Any],
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> AgentResponse:
        """Execute a workflow attached to the endpoint.

        When ``endpoint_def.workflow`` is set, the framework runs the
        workflow engine instead of the handler. The intent text is
        available via ``context.metadata["intent_raw"]``.
        """
        wf = endpoint_def.workflow
        assert wf is not None

        result = await wf.run(
            context=context,
            harness=self._harness,
            tools=self._tools,
        )

        if result.paused:
            return AgentResponse(
                result={
                    "status": "paused",
                    "paused_at_step": result.paused_at_step,
                    "workflow_id": result.workflow_id,
                    "steps_executed": result.steps_executed,
                    "state": result.final_state.model_dump(mode="json"),
                },
                status="pending_approval",
            )

        return AgentResponse(
            result={
                "status": "completed",
                "steps_executed": result.steps_executed,
                "duration_ms": result.total_duration_ms,
                "state": result.final_state.model_dump(mode="json"),
            },
            status="completed",
        )

    async def _execute_with_harness(
        self,
        intent: Intent[Any],
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> AgentResponse:
        """Execute intent through code generation and harness pipeline.

        Phase E4 — when the LLM returns a structured ``tool_calls``
        list with exactly one unambiguous call, the harness takes
        the **tool-first path**: skip code generation, dispatch the
        tool directly through :meth:`HarnessEngine.call_tool`, and
        return the tool's output. Everything else (multi-call plans,
        plain text responses, unknown tool names) falls through to
        the code-generation path for backward compatibility.

        Args:
            intent: The parsed intent.
            context: The agent execution context.
            endpoint_def: The endpoint definition.

        Returns:
            An AgentResponse.
        """
        assert self._harness is not None

        # Multi-turn agentic loop path. When tools are registered and
        # an LLM backend is available, use the agentic loop (ReAct
        # pattern) that iteratively dispatches tool calls through the
        # harness and feeds results back to the LLM until it produces
        # a final text answer. This supersedes the single-shot
        # tool-first path (E4) — which only handled exactly one tool
        # call — and makes the framework genuinely agentic.
        if self._tools is not None and self._llm is not None:
            tool_defs = self._tools.get_definitions()
            if tool_defs:
                loop_result = await self._run_agentic_loop(intent, context, endpoint_def)
                if loop_result is not None:
                    return loop_result

        # Lazy-init code generator for the fallback path.
        if self._code_generator is None:
            from agenticapi.runtime.code_generator import CodeGenerator

            self._code_generator = CodeGenerator(llm=self._llm, tools=self._tools)  # type: ignore[arg-type]

        # Pre-fetch data from tools (shared between code gen prompt and sandbox)
        sandbox_data: dict[str, object] = {}
        if self._tools is not None:
            for tool_def in self._tools.get_definitions():
                tool = self._tools.get(tool_def.name)
                try:
                    tool_result = await tool.invoke(query=f"SELECT * FROM {tool_def.name}")
                    sandbox_data[tool_def.name] = tool_result
                except Exception as exc:
                    logger.warning(
                        "tool_data_prefetch_failed",
                        tool=tool_def.name,
                        error=str(exc),
                    )
                    sandbox_data[tool_def.name] = []

        # Phase C5: approved-code cache lookup. Cache hits skip the
        # LLM call entirely and reuse the previously-approved code;
        # every downstream layer (policies, static analysis,
        # sandbox, monitors, validators) still runs so the cache is
        # strictly an LLM-call optimisation, never a safety
        # downgrade.
        cached_code: str | None = None
        cached_reasoning: str | None = None
        cached_confidence: float = 0.0
        cache_key: str | None = None
        if self._code_cache is not None:
            from agenticapi.observability import metrics as _metrics
            from agenticapi.runtime.code_cache import make_cache_key

            tool_names = list(self._tools._tools.keys()) if self._tools is not None else []
            policy_names = (
                [type(p).__name__ for p in self._harness._evaluator.policies] if self._harness is not None else []
            )
            cache_key = make_cache_key(
                endpoint_name=endpoint_def.name,
                intent_action=intent.action.value,
                intent_domain=intent.domain,
                tool_names=tool_names,
                policy_names=policy_names,
                intent_parameters=intent.parameters,
            )
            entry = self._code_cache.get(cache_key)
            if entry is not None:
                cached_code = entry.code
                cached_reasoning = entry.reasoning
                cached_confidence = entry.confidence
                _metrics.record_code_cache_hit(endpoint=endpoint_def.name)
                logger.info(
                    "code_cache_hit",
                    endpoint=endpoint_def.name,
                    cache_key=cache_key[:16],
                    hits=entry.hits,
                )
            else:
                _metrics.record_code_cache_miss(endpoint=endpoint_def.name)

        if cached_code is not None:
            generated_code = cached_code
            generated_reasoning = cached_reasoning
            generated_confidence = cached_confidence
        else:
            # Generate code (with data sample in prompt so LLM knows the schema)
            generated = await self._code_generator.generate(
                intent_raw=intent.raw,
                intent_action=intent.action.value,
                intent_domain=intent.domain,
                intent_parameters=intent.parameters,
                context=context,
                sandbox_data=sandbox_data if sandbox_data else None,
            )
            generated_code = generated.code
            generated_reasoning = generated.reasoning
            generated_confidence = generated.confidence

        # Execute through harness
        result = await self._harness.execute(
            intent_raw=intent.raw,
            intent_action=intent.action.value,
            intent_domain=intent.domain,
            generated_code=generated_code,
            reasoning=generated_reasoning,
            endpoint_name=endpoint_def.name,
            context=context,
            sandbox_data=sandbox_data if sandbox_data else None,
        )

        # Phase C5: populate the cache on a miss so the next
        # matching request is a hit. Only cache on successful
        # execution so failing code doesn't pollute the cache.
        if (
            self._code_cache is not None
            and cache_key is not None
            and cached_code is None
            and result.trace is not None
            and result.trace.error is None
        ):
            from agenticapi.runtime.code_cache import CachedCode

            self._code_cache.put(
                CachedCode(
                    key=cache_key,
                    code=generated_code,
                    reasoning=generated_reasoning,
                    confidence=generated_confidence,
                    created_at=datetime.now(tz=UTC),
                )
            )

        return AgentResponse(
            result=result.output,
            status="completed",
            generated_code=result.generated_code,
            reasoning=result.reasoning,
            confidence=generated_confidence,
            execution_trace_id=result.trace.trace_id if result.trace else None,
        )

    async def _run_agentic_loop(
        self,
        intent: Intent[Any],
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> AgentResponse | None:
        """Run the multi-turn agentic loop (ReAct pattern).

        Sends the user intent to the LLM with registered tool
        definitions. When the LLM returns tool calls, dispatches them
        through the harness and feeds results back. Repeats until the
        LLM produces a final text answer or the iteration limit is
        reached.

        Returns ``None`` when prerequisites are not met (no tools,
        no LLM, no harness), in which case the caller falls back to
        code generation.
        """
        if self._tools is None or self._llm is None or self._harness is None:
            return None

        from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt
        from agenticapi.runtime.loop import LoopConfig, run_agentic_loop

        tool_definitions = self._tools.get_definitions()
        if not tool_definitions:
            return None

        config = endpoint_def.loop_config or LoopConfig()

        # Enrich context metadata for the loop's harness calls.
        context.metadata["intent_raw"] = intent.raw
        context.metadata["intent_action"] = intent.action.value
        context.metadata["intent_domain"] = intent.domain

        prompt = LLMPrompt(
            system=(
                "You are an agent with access to a set of tools. "
                "Use the tools to help the user. When you have enough "
                "information to answer, respond with a final text answer. "
                "Think step by step about which tools to call."
            ),
            messages=[LLMMessage(role="user", content=intent.raw)],
        )

        # Extract budget policy from the harness if present.
        budget_policy = None
        pricing = None
        for policy in self._harness._evaluator.policies:
            from agenticapi.harness.policy.budget_policy import BudgetPolicy

            if isinstance(policy, BudgetPolicy):
                budget_policy = policy
                pricing = policy.pricing
                break

        try:
            result = await run_agentic_loop(
                llm=self._llm,
                tools=self._tools,
                harness=self._harness,
                prompt=prompt,
                config=config,
                budget_policy=budget_policy,
                pricing=pricing,
                context=context,
            )
        except Exception as exc:
            logger.warning(
                "agentic_loop_failed_falling_back",
                endpoint=endpoint_def.name,
                error=str(exc),
            )
            # Re-raise policy violations and budget errors; fall back
            # to code-gen for other failures.
            from agenticapi.exceptions import BudgetExceeded

            if isinstance(exc, (PolicyViolation, BudgetExceeded)):
                raise
            return None

        logger.info(
            "agentic_loop_completed",
            endpoint=endpoint_def.name,
            iterations=result.iterations,
            tool_calls=len(result.tool_calls_made),
            total_cost_usd=result.total_cost_usd,
        )
        return AgentResponse(
            result=result.final_text,
            status="completed",
            reasoning=json.dumps(
                [
                    {
                        "iteration": r.iteration,
                        "tool": r.tool_name,
                        "arguments": r.arguments,
                        "duration_ms": r.duration_ms,
                    }
                    for r in result.tool_calls_made
                ]
            )
            if result.tool_calls_made
            else None,
            confidence=1.0,
        )

    async def _try_tool_first_path(
        self,
        intent: Intent[Any],
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> AgentResponse | None:
        """Phase E4 — dispatch a single-tool LLM plan without code generation.

        Returns ``None`` when the tool-first path is not applicable
        (no tool registry, LLM returned no tool calls, multi-tool
        plan, unknown tool name). The caller falls back to the
        code-generation path in that case.
        """
        if self._tools is None or self._llm is None or self._harness is None:
            return None

        tool_definitions = self._tools.get_definitions()
        if not tool_definitions:
            return None

        from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

        prompt = LLMPrompt(
            system=(
                "You are an agent with access to a set of tools. When the "
                "user's intent can be satisfied by a single tool call, "
                "return exactly one function call with the correct arguments. "
                "Otherwise respond with plain text and the framework will "
                "fall back to code generation."
            ),
            messages=[LLMMessage(role="user", content=intent.raw)],
            tools=[
                {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": definition.parameters_schema,
                }
                for definition in tool_definitions
            ],
        )

        try:
            response = await self._llm.generate(prompt)
        except Exception as exc:
            # A failing LLM call should not kill the request — fall
            # through to code generation so the legacy path handles
            # whatever comes back.
            logger.warning(
                "tool_first_llm_generate_failed_falling_back",
                endpoint=endpoint_def.name,
                error=str(exc),
            )
            return None

        tool_calls = list(response.tool_calls)
        if len(tool_calls) != 1:
            return None

        call = tool_calls[0]
        try:
            tool = self._tools.get(call.name)
        except Exception as exc:
            logger.warning(
                "tool_first_unknown_tool_falling_back",
                endpoint=endpoint_def.name,
                tool=call.name,
                error=str(exc),
            )
            return None

        result = await self._harness.call_tool(
            tool=tool,
            arguments=dict(call.arguments),
            intent_raw=intent.raw,
            intent_action=intent.action.value,
            intent_domain=intent.domain,
            endpoint_name=endpoint_def.name,
            context=context,
        )
        logger.info(
            "tool_first_dispatched",
            endpoint=endpoint_def.name,
            tool=call.name,
            trace_id=result.trace.trace_id if result.trace else None,
        )
        return AgentResponse(
            result=result.output,
            status="completed",
            generated_code=result.generated_code,
            reasoning=None,
            confidence=response.confidence,
            execution_trace_id=result.trace.trace_id if result.trace else None,
        )

    async def _execute_handler_directly(
        self,
        intent: Intent[Any],
        context: AgentContext,
        endpoint_def: AgentEndpointDef,
    ) -> tuple[AgentResponse | Response, AgentTasks | None]:
        """Execute by calling the handler function directly.

        Used when no LLM is configured, for simple handler-based usage.
        Parameter injection is delegated to
        :mod:`agenticapi.dependencies` so the handler can use
        ``Depends(...)`` to receive arbitrary user-supplied
        dependencies, in addition to the built-in injected types
        (``Intent``, ``AgentContext``, ``AgentTasks``, ``UploadedFiles``,
        ``HtmxHeaders``).

        If the handler returns a Starlette ``Response`` or a ``FileResult``,
        it is passed through directly (no JSON wrapping). If the handler
        returns an :class:`AgentResponse` directly, it is also passed
        through unchanged so the caller can build the full response shape.

        Args:
            intent: The parsed intent.
            context: The agent execution context.
            endpoint_def: The endpoint definition.

        Returns:
            Tuple of (AgentResponse or Response, AgentTasks or None).
        """
        plan = endpoint_def.injection_plan or scan_handler(endpoint_def.handler)
        resolved = await solve(
            plan,
            intent=intent,
            context=context,
            files=context.metadata.get("files"),
            htmx_scope=context.metadata.get("scope"),
            overrides=self._dependency_overrides,
            route_dependencies=endpoint_def.dependencies or None,
        )
        tasks = resolved.tasks

        try:
            result = await invoke_handler(endpoint_def.handler, resolved)
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

        # Non-JSON response passthrough: bypass AgentResponse wrapping
        if isinstance(result, Response):
            return result, tasks
        if isinstance(result, (FileResult, HTMLResult, PlainTextResult)):
            return result.to_response(), tasks
        if isinstance(result, AgentResponse):
            # Handler already produced a fully-formed AgentResponse —
            # honour the existing convention of wrapping it once so
            # the JSON shape stays backward-compatible with consumers
            # that key off ``data["result"]["result"]``. The
            # ``response_model`` validation (D5) operates on the
            # inner result regardless of which form the handler used.
            return AgentResponse(
                result=self._validate_response(result.result, endpoint_def),
                status=result.status,
                generated_code=result.generated_code,
                reasoning=result.reasoning,
                confidence=result.confidence,
                execution_trace_id=result.execution_trace_id,
                follow_up_suggestions=result.follow_up_suggestions,
                error=result.error,
                approval_request=result.approval_request,
            ), tasks

        return AgentResponse(
            result=self._validate_response(result, endpoint_def),
            status="completed",
            confidence=intent.confidence,
        ), tasks

    def _validate_response(
        self,
        result: Any,
        endpoint_def: AgentEndpointDef,
    ) -> Any:
        """Coerce a handler return value through the endpoint's ``response_model``.

        When ``response_model`` is unset (the default), returns ``result``
        unchanged so the framework stays backward-compatible.
        """
        model = endpoint_def.response_model
        if model is None or result is None:
            return result
        # Already an instance — validate (re-parses, but cheap) and return.
        if isinstance(result, model):
            return result.model_dump(mode="json")
        # Coerce dicts and other mappings into the declared model.
        try:
            return model.model_validate(result).model_dump(mode="json")
        except Exception as exc:
            logger.error(
                "response_model_validation_failed",
                endpoint_name=endpoint_def.name,
                model=model.__name__,
                error=str(exc),
            )
            raise

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
            # Phase F5: every streaming endpoint gets a companion
            # POST /agent/{name}/resume/{stream_id} route. The
            # handler is identical for every streaming endpoint
            # because all the routing logic happens via stream_id;
            # we capture the endpoint name in a closure for logging.
            if endpoint_def.streaming is not None:
                routes.append(
                    Route(
                        f"/agent/{name}/resume/{{stream_id}}",
                        self._make_resume_handler(name),
                        methods=["POST"],
                    )
                )
                # Phase F7: GET /agent/{name}/stream/{stream_id} replays
                # the persisted event log then tails live events. The
                # transport (SSE / NDJSON) is selected via the
                # ``transport`` query parameter, defaulting to the
                # endpoint's declared streaming transport.
                routes.append(
                    Route(
                        f"/agent/{name}/stream/{{stream_id}}",
                        self._make_stream_reconnect_handler(name, endpoint_def.streaming),
                        methods=["GET"],
                    )
                )

        routes.extend(self._extra_routes)
        routes.append(Route("/health", self._health_handler, methods=["GET"]))
        routes.append(Route("/capabilities", self._capabilities_handler, methods=["GET"]))

        # Prometheus metrics endpoint (Phase A2). Only registered when
        # the app constructor was given a metrics_url. The route always
        # responds 200 — when the optional metrics deps are missing,
        # it serves an empty exposition rather than 404.
        if self._metrics_url is not None:
            routes.append(Route(self._metrics_url, self._metrics_handler, methods=["GET"]))

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

        # Playground routes (Element 3).
        if self._playground_routes:
            routes.extend(self._playground_routes)

        # Trace inspector routes.
        if self._trace_inspector_routes:
            routes.extend(self._trace_inspector_routes)

        lifespan_managers = list(self._lifespan_managers)

        @asynccontextmanager
        async def lifespan(app: Starlette):  # type: ignore[no-untyped-def]
            async with AsyncExitStack() as stack:
                # Enter all registered sub-app lifespan context managers
                # (e.g. mounted FastMCP server's session manager).
                for factory in lifespan_managers:
                    await stack.enter_async_context(factory())
                await self._on_startup()
                try:
                    yield
                finally:
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

            # Phase F2: streaming branch. When the endpoint declared
            # ``streaming="sse"`` (or another transport), the request
            # follows a parallel path that creates an AgentStream,
            # injects it into the handler, and returns a Starlette
            # StreamingResponse instead of a JSON blob.
            if endpoint_def.streaming is not None:
                try:
                    return await self._process_intent_streaming(
                        raw_intent,
                        endpoint_def=endpoint_def,
                        session_id=session_id,
                        auth_user=auth_user,
                        files=uploaded_files,
                        scope=dict(request.scope, headers=list(request.headers.raw)),
                    )
                except AgenticAPIError as exc:
                    status_code = EXCEPTION_STATUS_MAP.get(type(exc), 500)
                    return JSONResponse(
                        {"error": str(exc), "status": "error"},
                        status_code=status_code,
                    )
                except Exception as exc:
                    logger.error(
                        "streaming_endpoint_unhandled_error",
                        endpoint_name=name,
                        error=str(exc),
                    )
                    return JSONResponse(
                        {"error": "Internal server error", "status": "error"},
                        status_code=500,
                    )

            try:
                response = await self.process_intent(
                    raw_intent,
                    endpoint_name=name,
                    session_id=session_id,
                    auth_user=auth_user,
                    files=uploaded_files,
                    _scope=dict(request.scope, headers=list(request.headers.raw)),
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

    async def _metrics_handler(self, request: Request) -> Response:
        """Prometheus exposition endpoint (Phase A2).

        Serves the canonical AgenticAPI metric set when
        ``opentelemetry-sdk`` + ``opentelemetry-exporter-prometheus``
        are installed; serves an empty body otherwise (still 200 so
        scrapers don't alarm during incremental rollouts).
        """
        del request
        from agenticapi.observability import render_prometheus_exposition

        body, content_type = render_prometheus_exposition()
        return Response(content=body, media_type=content_type)

    def _make_stream_reconnect_handler(
        self,
        endpoint_name: str,
        default_transport: str,
    ) -> Callable[[Request], Awaitable[Response]]:
        """Build the Phase F7 resume handler for a streaming endpoint.

        Returns a Starlette route handler that tails the persistent
        :class:`StreamStore` for a given ``stream_id``. Clients pick
        up where they left off by passing ``?since=<seq>``; the
        default ``-1`` replays the entire log. The transport
        (``sse`` or ``ndjson``) is selected via ``?transport=...``
        and defaults to the endpoint's declared streaming transport.

        The handler returns 404 when ``stream_id`` is unknown, 200
        with an empty body when the stream exists but has already
        been discarded (e.g. TTL expired), and a streaming body
        otherwise. Completion of the underlying stream causes the
        response body to close cleanly after the terminal event.
        """

        async def reconnect_handler(request: Request) -> Response:
            from starlette.responses import StreamingResponse

            from agenticapi.interface.stream_store import tail_from

            stream_id = request.path_params.get("stream_id", "")
            since_raw = request.query_params.get("since", "-1")
            try:
                since_seq = int(since_raw)
            except ValueError:
                return JSONResponse(
                    {"error": "Invalid 'since' query parameter (must be an integer)", "status": "error"},
                    status_code=400,
                )

            transport_param = request.query_params.get("transport") or default_transport
            transport = transport_param.lower()

            # Defensive 404 path: when the stream_id is completely
            # unknown we don't want to open a long-polling body that
            # hangs forever. We probe by asking for events first.
            initial = await self._stream_store.get_after(stream_id, -1)
            complete = await self._stream_store.is_complete(stream_id)
            if not initial and not complete:
                return JSONResponse(
                    {
                        "error": f"No stream found for stream_id={stream_id}",
                        "status": "error",
                    },
                    status_code=404,
                )

            if transport == "ndjson":
                media_type = "application/x-ndjson"
                render = _ndjson_event_bytes
            else:
                media_type = "text/event-stream"
                render = _sse_event_bytes

            async def body() -> Any:
                async for event in tail_from(self._stream_store, stream_id, since_seq=since_seq):
                    yield render(event)

            logger.info(
                "stream_reconnect_opened",
                endpoint=endpoint_name,
                stream_id=stream_id,
                since=since_seq,
                transport=transport,
            )
            return StreamingResponse(
                body(),
                media_type=media_type,
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                },
            )

        return reconnect_handler

    def _make_resume_handler(self, endpoint_name: str) -> Callable[[Request], Awaitable[Response]]:
        """Build the Phase F5 resume handler for one streaming endpoint.

        Returns a Starlette route handler bound to ``endpoint_name``.
        Each streaming endpoint gets its own resume route via
        :meth:`_build_starlette` so the URL stays scoped to the
        endpoint and shows up in OpenAPI/capabilities tied to its
        owner.
        """

        async def resume_handler(request: Request) -> Response:
            stream_id = request.path_params.get("stream_id", "")
            try:
                body = await request.json()
            except json.JSONDecodeError:
                return JSONResponse(
                    {"error": "Invalid JSON body", "status": "error"},
                    status_code=400,
                )
            decision = body.get("decision") if isinstance(body, dict) else None
            approval_id = body.get("approval_id") if isinstance(body, dict) else None
            if not decision or not isinstance(decision, str):
                return JSONResponse(
                    {"error": "Missing 'decision' field in request body", "status": "error"},
                    status_code=400,
                )
            resolved = await self._approval_registry.resolve(
                stream_id,
                decision,
                approval_id=approval_id if isinstance(approval_id, str) else None,
            )
            if not resolved:
                return JSONResponse(
                    {
                        "error": (
                            f"No pending approval found for stream_id={stream_id}"
                            + (f" approval_id={approval_id}" if approval_id else "")
                        ),
                        "status": "error",
                    },
                    status_code=404,
                )
            logger.info(
                "approval_resume_accepted",
                endpoint=endpoint_name,
                stream_id=stream_id,
                decision=decision,
            )
            return JSONResponse({"status": "resolved", "decision": decision})

        return resume_handler

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


def _sse_event_bytes(event: dict[str, Any]) -> bytes:
    """Render one persisted event dict as an SSE frame.

    Mirror of :func:`agenticapi.interface.transports.sse.event_to_sse_frame`
    but operates on the already-dumped dict that the stream store
    hands back, so the reconnect handler doesn't have to reconstruct
    a Pydantic model just to serialise it.
    """
    kind = event.get("kind", "event")
    body = json.dumps(event, ensure_ascii=False)
    return f"event: {kind}\ndata: {body}\n\n".encode()


def _ndjson_event_bytes(event: dict[str, Any]) -> bytes:
    """Render one persisted event dict as an NDJSON line."""
    return (json.dumps(event, ensure_ascii=False) + "\n").encode()


def _headers_from_scope(scope: dict[str, Any] | None) -> dict[str, str] | None:
    """Pull HTTP headers out of an ASGI scope dict as a flat str→str map.

    The scope's ``headers`` field is a list of ``(name_bytes, value_bytes)``
    tuples per the ASGI spec. We decode them into a case-insensitive
    (lowercased) dict so the W3C Trace Context propagator can find
    ``traceparent`` regardless of how the upstream client cased it.
    Returns ``None`` when ``scope`` is ``None`` or has no headers.
    """
    if not scope:
        return None
    raw_headers = scope.get("headers")
    if not raw_headers:
        return None
    out: dict[str, str] = {}
    for entry in raw_headers:
        try:
            name, value = entry
        except (TypeError, ValueError):
            continue
        if isinstance(name, bytes):
            name = name.decode("latin-1")
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        out[str(name).lower()] = str(value)
    return out
