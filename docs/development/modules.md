# Module Reference

## Source Structure

```
src/agenticapi/
    __init__.py              Public API exports (AgenticApp, Intent, policies, etc.)
    app.py                   AgenticApp — main ASGI application
    routing.py               AgentRouter — endpoint grouping with prefix/tags
    types.py                 AutonomyLevel, TraceLevel, Severity enums; JSON/Headers type aliases
    exceptions.py            Exception hierarchy with HTTP status code mapping
    openapi.py               OpenAPI 3.1 schema generation, Swagger UI, ReDoc
    params.py                HarnessDepends — dependency injection marker
    _compat.py               Python version check (requires 3.13+)

    security.py              Authentication: APIKeyHeader, HTTPBearer, Authenticator, AuthUser

    interface/
        intent.py            Intent, IntentAction, IntentParser, IntentScope
        response.py          AgentResponse, FileResult, HTMLResult, PlainTextResult, ResponseFormatter
        upload.py            UploadFile, UploadedFiles — file upload types
        htmx.py              HtmxHeaders, htmx_response_headers — HTMX support
        tasks.py             AgentTasks — background task accumulator
        session.py           Session, SessionManager (in-memory with TTL)
        endpoint.py          AgentEndpointDef (endpoint configuration dataclass)
        compat/
            rest.py          RESTCompat, expose_as_rest — REST route generation
            fastapi.py       mount_fastapi, mount_in_agenticapi — ASGI mount
            mcp.py           MCPCompat, expose_as_mcp — MCP server (optional: pip install agenticapi[mcp])
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
            anthropic.py     AnthropicBackend (Claude) with timeout
            openai.py        OpenAIBackend (GPT) with timeout, max_completion_tokens
            gemini.py        GeminiBackend (Gemini) with timeout
            mock.py          MockBackend — FIFO response queue for testing
        tools/
            base.py          Tool protocol, ToolDefinition, ToolCapability enum
            registry.py      ToolRegistry — centralized tool registration and lookup
            database.py      DatabaseTool — SQL execution with read-only mode, comment-stripped write detection
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

```python
# Core
AgenticApp, AgentRouter, AgentContext, AgentResponse, AgentTasks

# Intent
Intent, IntentAction, IntentParser, IntentScope

# File handling & custom responses
FileResult, HTMLResult, PlainTextResult, UploadFile, UploadedFiles

# HTMX
HtmxHeaders, htmx_response_headers

# Security
APIKeyHeader, APIKeyQuery, HTTPBearer, HTTPBasic
AuthCredentials, AuthUser, Authenticator

# Harness
HarnessEngine, CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
ApprovalRule, ApprovalWorkflow

# Exceptions
AgenticAPIError, HarnessError, PolicyViolation, SandboxViolation
ApprovalRequired, ApprovalDenied, ApprovalTimeout
AuthenticationError, AuthorizationError
CodeGenerationError, CodeExecutionError, ToolError
IntentParseError, SessionError

# Types
AutonomyLevel, TraceLevel, Severity
```
