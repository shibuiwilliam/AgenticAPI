# Module Reference

## Source Structure (81 files, 10,613 lines)

```
src/agenticapi/
    __init__.py              Public API exports (48 symbols)
    app.py                   AgenticApp — main ASGI application (844 lines)
    routing.py               AgentRouter — endpoint grouping with prefix/tags
    types.py                 AutonomyLevel, TraceLevel, Severity enums; JSON/Headers type aliases
    exceptions.py            Exception hierarchy with HTTP status code mapping
    openapi.py               OpenAPI 3.1.0 schema generation, Swagger UI, ReDoc
    security.py              Authenticator, AuthUser, APIKeyHeader, HTTPBearer, HTTPBasic
    params.py                HarnessDepends — dependency injection marker
    _compat.py               Python version check (requires 3.13+)

    interface/
        intent.py            Intent, IntentAction, IntentParser, IntentScope
        response.py          AgentResponse, ResponseFormatter, FileResult, HTMLResult, PlainTextResult
        session.py           Session, SessionManager (in-memory with TTL)
        endpoint.py          AgentEndpointDef (endpoint configuration dataclass)
        tasks.py             AgentTasks — background tasks (like FastAPI's BackgroundTasks)
        upload.py            UploadFile, UploadedFiles — multipart file upload support
        htmx.py              HtmxHeaders, htmx_response_headers — HTMX request/response support
        compat/
            rest.py          RESTCompat, expose_as_rest — REST route generation
            fastapi.py       mount_fastapi, mount_in_agenticapi — ASGI mount
            mcp.py           MCPCompat, expose_as_mcp — MCP server (pip install agenticapi[mcp])
        a2a/
            protocol.py      A2AMessage, A2AMessageType, A2ARequest, A2AResponse
            capability.py    Capability, CapabilityRegistry
            trust.py         TrustPolicy, TrustScorer

    harness/
        engine.py            HarnessEngine — orchestrates the full safety pipeline
        policy/
            base.py          Policy (base class), PolicyResult
            code_policy.py   CodePolicy — AST-based import/eval/exec/network checks
            data_policy.py   DataPolicy — SQL table/column access, DDL prevention
            resource_policy.py  ResourcePolicy — loop depth, memory, CPU limits
            runtime_policy.py   RuntimePolicy — code complexity (AST node count)
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
            recorder.py      AuditRecorder — bounded in-memory storage (max_traces)
            exporters.py     AuditExporter protocol, ConsoleExporter, OpenTelemetryExporter, CompositeExporter

    runtime/
        code_generator.py    CodeGenerator — LLM-powered code generation with prompt templates
        context.py           AgentContext, ContextItem, ContextWindow (token budget)
        llm/
            base.py          LLMBackend protocol, LLMMessage, LLMPrompt, LLMResponse, LLMChunk, LLMUsage
            anthropic.py     AnthropicBackend (Claude, default: claude-sonnet-4-6)
            openai.py        OpenAIBackend (GPT, default: gpt-5.4-mini)
            gemini.py        GeminiBackend (Gemini, default: gemini-2.5-flash)
            mock.py          MockBackend — FIFO response queue for testing
        tools/
            base.py          Tool protocol, ToolDefinition, ToolCapability enum
            registry.py      ToolRegistry — centralized tool registration and lookup
            database.py      DatabaseTool — SQL execution with read-only mode
            http_client.py   HttpClientTool — httpx wrapper with allowed_hosts
            cache.py         CacheTool — in-memory TTL cache with FIFO eviction
            queue.py         QueueTool — async queue with named channels
        prompts/
            code_generation.py  Prompt templates for code generation (XML-escaped, data sample)
            intent_parsing.py   Prompt templates for intent parsing (XML-escaped)

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
```

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
│   └── ContextError            -> HTTP 500
├── InterfaceError
│   ├── IntentParseError        -> HTTP 400
│   ├── SessionError            -> HTTP 400
│   └── A2AError                -> HTTP 502
├── AuthenticationError         -> HTTP 401
└── AuthorizationError          -> HTTP 403
```

## Public API (`from agenticapi import ...`)

```python
# Core
AgenticApp, AgentRouter, AgentContext, AgentResponse, AgentTasks

# Intent
Intent, IntentAction, IntentParser, IntentScope

# Harness
HarnessEngine, CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
ApprovalRule, ApprovalWorkflow

# Security
Authenticator, AuthUser, AuthCredentials
APIKeyHeader, APIKeyQuery, HTTPBearer, HTTPBasic

# File handling
FileResult, UploadFile, UploadedFiles

# Custom responses
HTMLResult, PlainTextResult

# HTMX
HtmxHeaders, htmx_response_headers

# Exceptions
AgenticAPIError, HarnessError, PolicyViolation, SandboxViolation
ApprovalRequired, ApprovalDenied, ApprovalTimeout
AuthenticationError, AuthorizationError
CodeGenerationError, CodeExecutionError, ToolError
IntentParseError, SessionError

# Types
AutonomyLevel, TraceLevel, Severity

# Version
__version__  # "0.1.0"
```
