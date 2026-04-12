# Module Reference

## Source Structure (118 Python modules, ~21,944 lines)

The package ships a `py.typed` marker (PEP 561) so downstream mypy users pick up inline type annotations.

```
src/agenticapi/
    __init__.py              Public API exports (73 symbols) — see Public API below
    py.typed                 PEP 561 type info marker
    app.py                   AgenticApp — main ASGI application
    routing.py               AgentRouter — endpoint grouping, route-level dependencies
    types.py                 AutonomyLevel, TraceLevel, Severity enums; JSON/Headers type aliases
    exceptions.py            Exception hierarchy with HTTP status code mapping
    openapi.py               OpenAPI 3.1 schema generation, Swagger UI, ReDoc
    params.py                HarnessDepends — legacy dependency injection marker
    _compat.py               Python version check (requires 3.13+)

    security.py              Authentication: APIKeyHeader, HTTPBearer, Authenticator, AuthUser

    dependencies/
        depends.py           Depends(), Dependency — FastAPI-style handler injection
        scanner.py           scan_handler() — compile handler signatures into InjectionPlan
        solver.py            solve() — resolve deps per-request with async teardown

    interface/
        intent.py            Intent, Intent[T] typed payloads, IntentAction, IntentParser, IntentScope
        response.py          AgentResponse, FileResult, HTMLResult, PlainTextResult, ResponseFormatter
        upload.py            UploadFile, UploadedFiles — file upload types
        htmx.py              HtmxHeaders, htmx_response_headers — HTMX support
        tasks.py             AgentTasks — background task accumulator
        session.py           Session, SessionManager (in-memory with TTL)
        endpoint.py          AgentEndpointDef (endpoint configuration dataclass)
        stream.py            AgentStream, AgentEvent, approval + autonomy event types
        stream_store.py      InMemoryStreamStore, StreamStore — replayable event storage
        approval_registry.py ApprovalRegistry — in-process pause/resume coordination
        transports/
            sse.py           SSE framing and streaming response helpers
            ndjson.py        NDJSON framing and streaming response helpers
        compat/
            rest.py          RESTCompat, expose_as_rest — REST route generation
            fastapi.py       mount_fastapi, mount_in_agenticapi — ASGI mount
            mcp.py           MCPCompat, expose_as_mcp — MCP server (optional: pip install agentharnessapi[mcp])
        a2a/
            protocol.py      A2AMessage, A2AMessageType, A2ARequest, A2AResponse
            capability.py    Capability, CapabilityRegistry
            trust.py         TrustPolicy, TrustScorer

    harness/
        engine.py            HarnessEngine — orchestrates the full safety pipeline
        policy/
            base.py          Policy (base class), PolicyResult
            autonomy_policy.py  AutonomyPolicy, AutonomySignal, EscalateWhen
            code_policy.py   CodePolicy — AST-based import/eval/exec/network checks
            data_policy.py   DataPolicy — SQL table/column access, DDL prevention
            resource_policy.py  ResourcePolicy — loop depth, memory, CPU limits
            runtime_policy.py   RuntimePolicy — code complexity (AST node count)
            budget_policy.py    BudgetPolicy — per-request/session/user/endpoint cost caps, SpendStore
            pricing.py       PricingRegistry, ModelPricing — per-1k-token pricing (April 2026 snapshot)
            evaluator.py     PolicyEvaluator — aggregates multiple policies
        sandbox/
            base.py          SandboxRuntime (ABC), ResourceLimits, ResourceMetrics, SandboxResult
            process.py       ProcessSandbox — subprocess execution with timeout, base64 transport
            static_analysis.py  check_code_safety() — AST analysis for dangerous patterns
            monitors.py      ExecutionMonitor protocol, ResourceMonitor, OutputSizeMonitor
            validators.py    ResultValidator protocol, OutputTypeValidator, ReadOnlyValidator
        approval/
            rules.py         ApprovalRule — declarative approval requirements
            workflow.py      ApprovalWorkflow — lifecycle management with async lock
            notifiers.py     ApprovalNotifier protocol, LogNotifier
        audit/
            trace.py         ExecutionTrace — full operation lifecycle capture
            recorder.py      AuditRecorder protocol, InMemoryAuditRecorder (bounded)
            sqlite_store.py  SqliteAuditRecorder — persistent SQLite-backed storage
            exporters.py     AuditExporter protocol, ConsoleExporter, OpenTelemetryExporter, CompositeExporter

    observability/
        tracing.py           configure_tracing, get_tracer — OpenTelemetry span setup
        metrics.py           configure_metrics, record_*, render_prometheus_exposition
        propagation.py       extract/inject_context_from/into_headers — W3C traceparent propagation
        semconv.py           GenAIAttributes, AgenticAPIAttributes, SpanNames — semantic conventions

    runtime/
        code_generator.py    CodeGenerator — LLM-powered code generation with prompt templates
        context.py           AgentContext, ContextItem, ContextWindow (token budget)
        llm/
            base.py          LLMBackend protocol, LLMMessage, LLMPrompt, LLMResponse, LLMChunk, LLMUsage, ToolCall
            anthropic.py     AnthropicBackend (Claude) with timeout, text + tools pass-through
            openai.py        OpenAIBackend (GPT) with timeout, text + tools pass-through
            gemini.py        GeminiBackend (Gemini) with timeout, text generation backend
            retry.py         RetryConfig, with_retry — async exponential backoff for transient errors
            mock.py          MockBackend — FIFO response queue + tool-call responses for testing
        tools/
            base.py          Tool protocol, ToolDefinition, ToolCapability enum
            registry.py      ToolRegistry — centralized tool registration and lookup
            decorator.py     @tool decorator — turn plain functions into tools (auto JSON schema)
            database.py      DatabaseTool — SQL execution with read-only mode, comment-stripped write detection
            http_client.py   HttpClientTool — httpx wrapper with allowed_hosts
            cache.py         CacheTool — in-memory TTL cache with FIFO eviction
            queue.py         QueueTool — async queue with named channels
        prompts/
            code_generation.py  Prompt templates for code generation (XML-escaped, data sample)
            intent_parsing.py   Prompt templates for intent parsing (XML-escaped)

    mesh/
        mesh.py              AgentMesh — multi-agent orchestration container
        context.py           MeshContext, MeshCycleError — inter-role calls

    application/
        pipeline.py          DynamicPipeline, PipelineStage, PipelineResult

    ops/
        base.py              OpsAgent (ABC), OpsHealthStatus

    testing/
        agent_test_case.py   AgentTestCase — pytest-compatible base class
        assertions.py        assert_code_safe, assert_intent_parsed, assert_policy_enforced
        mocks.py             mock_llm context manager, MockSandbox
        benchmark.py         BenchmarkRunner, BenchmarkResult
        fixtures.py          create_test_app factory

    cli/
        main.py              CLI entry point (dev, console, version subcommands)
        dev.py               Development server (uvicorn wrapper)
        console.py           Interactive REPL console
        replay.py            Replay helper CLI for stored stream/audit data
```

## Extensions

Heavyweight integrations live in the top-level `extensions/` directory as separate, independently-versioned packages. They are NOT part of the core `agenticapi` package.

```
extensions/
    agenticapi-claude-agent-sdk/    Claude Agent SDK runner with policy bridging
        pyproject.toml              Independent package
        src/agenticapi_claude_agent_sdk/
            runner.py               ClaudeAgentRunner — full agentic loop in an endpoint
            backend.py              ClaudeAgentSDKBackend — LLMBackend adapter
            permissions.py          HarnessPermissionAdapter — policies → SDK can_use_tool
            tools.py                build_sdk_mcp_server_from_registry
            messages.py             collect_session, stream_session_events
            options.py              SDK options builders
            exceptions.py           ClaudeAgentSDKError, ClaudeAgentSDKNotInstalledError
```

See the [Extensions guide](extensions.md) for installation and how to build your own.

## Exception Hierarchy

```
AgenticAPIError
├── HarnessError
│   ├── PolicyViolation         -> HTTP 403
│   ├── SandboxViolation        -> HTTP 403
│   ├── ApprovalRequired        -> HTTP 202 (with request_id, approvers)
│   ├── ApprovalDenied          -> HTTP 403
│   └── ApprovalTimeout         -> HTTP 408
├── AgentRuntimeError
│   ├── CodeGenerationError     -> HTTP 500
│   ├── CodeExecutionError      -> HTTP 500
│   ├── ToolError               -> HTTP 502
│   └── ContextError            -> HTTP 500 (default)
└── InterfaceError
    ├── IntentParseError        -> HTTP 400
    ├── SessionError            -> HTTP 400
    ├── A2AError                -> HTTP 502
    ├── AuthenticationError     -> HTTP 401
    └── AuthorizationError      -> HTTP 403
```

## Public API (`from agenticapi import ...`)

59 symbols exported from the top-level package via `__all__`:

```python
# Core
AgenticApp, AgentRouter, AgentContext, AgentEvent, AgentResponse, AgentStream, AgentTasks

# Intent
Intent, IntentAction, IntentParser, IntentScope  # Intent is generic: Intent[T]

# Dependency injection (FastAPI-style)
Depends, Dependency

# Tool decorator
tool

# File handling & custom responses
FileResult, HTMLResult, PlainTextResult, UploadFile, UploadedFiles

# HTMX
HtmxHeaders, htmx_response_headers

# Security
APIKeyHeader, APIKeyQuery, HTTPBearer, HTTPBasic
AuthCredentials, AuthUser, Authenticator

# Harness
HarnessEngine, CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
AutonomyPolicy, AutonomySignal, EscalateWhen
BudgetPolicy, PricingRegistry
ApprovalRule, ApprovalWorkflow

# Exceptions
AgenticAPIError, HarnessError, PolicyViolation, SandboxViolation
ApprovalRequired, ApprovalDenied, ApprovalTimeout
BudgetExceeded
AuthenticationError, AuthorizationError
CodeGenerationError, CodeExecutionError, ToolError
IntentParseError, SessionError

# Types
AutonomyLevel, TraceLevel, Severity
```

Observability helpers live under the `agenticapi.observability` subpackage rather than the top-level namespace:

```python
from agenticapi.observability import (
    configure_tracing, configure_metrics,
    record_request, record_llm_usage, record_policy_denial,
    extract_context_from_headers, inject_context_into_headers, headers_with_traceparent,
    is_propagation_available,
    GenAIAttributes, AgenticAPIAttributes, SpanNames,
)
```

Persistent audit storage and the native tool-call data types sit one level deeper, next to the rest of their domain:

```python
from agenticapi.harness.audit import (
    AuditRecorderProtocol,
    InMemoryAuditRecorder,
    SqliteAuditRecorder,
    ExecutionTrace,
)

from agenticapi.runtime.llm.base import ToolCall   # native function-call dataclass
```
