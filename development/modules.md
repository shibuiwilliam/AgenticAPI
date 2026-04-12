# Module Reference

Complete reference for every Python module in `src/agenticapi/`, organized by subpackage. Each entry lists the file path, purpose, and key exports.

---

## Root Package

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Public API surface; re-exports ~80 symbols from all subpackages | `AgenticApp`, `AgentRouter`, `Intent`, `AgentResponse`, `HarnessEngine`, `CodePolicy`, `Depends`, `tool`, etc. |
| `_compat.py` | Python version check (side-effect import, raises on <3.13) | `MIN_PYTHON_VERSION` |
| `app.py` | Main ASGI application class; integrates all layers | `AgenticApp` |
| `routing.py` | Endpoint grouping (analogous to FastAPI's `APIRouter`) | `AgentRouter` |
| `exceptions.py` | Shared exception hierarchy with HTTP status code mapping | `AgenticAPIError`, `PolicyViolation`, `ApprovalRequired`, `BudgetExceeded`, `AuthenticationError`, `SandboxViolation`, `ToolError`, etc. |
| `types.py` | Shared enums used across layers | `AutonomyLevel`, `Severity`, `TraceLevel` |
| `params.py` | Query/Header parameter extraction helpers | `Query`, `Header` |
| `openapi.py` | OpenAPI 3.1.0 schema generation for agent endpoints | `generate_openapi_schema` |
| `security.py` | Authentication schemes and orchestrator | `Authenticator`, `AuthUser`, `AuthCredentials`, `APIKeyHeader`, `APIKeyQuery`, `HTTPBearer`, `HTTPBasic` |

---

## `interface/` — HTTP Request/Response Types

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports all interface types | (see below) |
| `intent.py` | Intent parsing: keyword-based and LLM-based classification | `Intent`, `IntentAction` (StrEnum), `IntentParser`, `IntentScope` |
| `endpoint.py` | Endpoint definition dataclass | `AgentEndpointDef` |
| `response.py` | Response types and formatting | `AgentResponse`, `ResponseFormatter`, `FileResult`, `HTMLResult`, `PlainTextResult` |
| `tasks.py` | Background task runner (post-response execution) | `AgentTasks` |
| `upload.py` | File upload types | `UploadFile`, `UploadedFiles` |
| `session.py` | In-memory session management for multi-turn conversations | `Session`, `SessionManager`, `SessionState` |
| `stream.py` | Streaming event schema and handler-side helper | `AgentStream`, `AgentEvent`, `ThoughtEvent`, `ToolCallStartedEvent`, `ToolCallCompletedEvent`, `PartialResultEvent`, `ApprovalRequestedEvent`, `ApprovalResolvedEvent`, `FinalEvent`, `ErrorEvent`, `AutonomyChangedEvent`, `ApprovalHandle` |
| `stream_store.py` | Persistent event log for reconnect/resume | `StreamStore` (Protocol), `InMemoryStreamStore` |
| `approval_registry.py` | In-process registry of pending approval handles | `ApprovalRegistry` |
| `htmx.py` | HTMX request header parsing and response header builder | `HtmxHeaders`, `htmx_response_headers` |

### `interface/transports/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Package marker | |
| `sse.py` | Server-Sent Events wire format transport | `run_sse_response`, `event_to_sse_frame` |
| `ndjson.py` | Newline-delimited JSON wire format transport | `run_ndjson_response`, `event_to_ndjson_line` |

### `interface/compat/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Package marker | |
| `mcp.py` | MCP server compatibility (requires `agenticapi[mcp]`) | `MCPCompat`, `expose_as_mcp` |
| `rest.py` | REST route generation from agent endpoints | `RESTCompat` |
| `fastapi.py` | FastAPI interop helpers | `to_fastapi_router` |

### `interface/a2a/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Package marker | |
| `capability.py` | Agent capability advertisement | `AgentCapability` |
| `protocol.py` | Agent-to-agent protocol definitions | `A2AProtocol` |
| `trust.py` | Inter-agent trust model | `TrustLevel` |

---

## `dependencies/` — Dependency Injection

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports DI types | (see below) |
| `depends.py` | `Depends()` sentinel and `Dependency` dataclass | `Depends`, `Dependency` |
| `scanner.py` | Registration-time handler signature scanner | `scan_handler`, `InjectionPlan`, `InjectionKind`, `ParamPlan` |
| `solver.py` | Request-time dependency resolution and handler invocation | `solve`, `invoke_handler`, `ResolvedHandlerCall`, `DependencyResolutionError` |

---

## `harness/` — Safety and Governance

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports all harness types | (see below) |
| `engine.py` | Central orchestrator: policy -> static analysis -> sandbox -> audit | `HarnessEngine`, `ExecutionResult` |

### `harness/policy/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports all policy types | |
| `base.py` | Policy protocol and result types | `Policy` (Protocol), `PolicyResult` |
| `evaluator.py` | Aggregates results from multiple policies | `PolicyEvaluator`, `EvaluationResult` |
| `code_policy.py` | Import and eval/exec restrictions | `CodePolicy` |
| `data_policy.py` | SQL table/column access control, DDL denial | `DataPolicy` |
| `resource_policy.py` | CPU/memory/time limits | `ResourcePolicy` |
| `runtime_policy.py` | AST complexity limits (max depth, max nodes) | `RuntimePolicy` |
| `budget_policy.py` | Per-request/session/user cost ceilings | `BudgetPolicy`, `BudgetEvaluationContext`, `CostEstimate`, `SpendStore`, `InMemorySpendStore` |
| `pricing.py` | LLM token-cost pricing table | `PricingRegistry`, `ModelPricing` |
| `prompt_injection_policy.py` | Regex-based prompt injection detection | `PromptInjectionPolicy`, `InjectionHit` |
| `pii_policy.py` | PII detection (email, phone, SSN, credit card, IBAN, IPv4) | `PIIPolicy`, `PIIHit`, `redact_pii` |
| `autonomy_policy.py` | Live autonomy escalation rules | `AutonomyPolicy`, `AutonomySignal`, `AutonomyState`, `EscalateWhen` |

### `harness/sandbox/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports sandbox types | |
| `base.py` | Abstract sandbox runtime and result types | `SandboxRuntime` (ABC), `SandboxResult`, `ResourceLimits`, `ResourceMetrics` |
| `process.py` | Subprocess-based sandbox with base64 code transport | `ProcessSandbox` |
| `static_analysis.py` | AST-based safety analysis (pre-execution) | `check_code_safety`, `SafetyResult`, `SafetyViolation` |
| `monitors.py` | Post-execution resource monitors | `ExecutionMonitor`, `ResourceMonitor`, `OutputSizeMonitor` |
| `validators.py` | Post-execution output validators | `ResultValidator`, `TypeValidator` |

### `harness/approval/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports approval types | |
| `workflow.py` | Human-in-the-loop approval engine | `ApprovalWorkflow`, `ApprovalRequest`, `ApprovalState` |
| `rules.py` | Declarative approval rule matching | `ApprovalRule` |
| `notifiers.py` | Notification backends for approval requests | `ApprovalNotifier` (Protocol), `LogNotifier` |

### `harness/audit/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports audit types | |
| `trace.py` | Execution trace data model | `ExecutionTrace` |
| `recorder.py` | In-memory bounded-buffer audit recorder | `AuditRecorder`, `AuditRecorderProtocol`, `InMemoryAuditRecorder` |
| `sqlite_store.py` | SQLite-backed persistent audit recorder | `SqliteAuditRecorder` |
| `exporters.py` | Audit trace export formats | `AuditExporter` |

---

## `runtime/` — Execution Infrastructure

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports runtime types | |
| `context.py` | Per-request execution context | `AgentContext`, `ContextItem`, `ContextWindow` |
| `code_generator.py` | LLM-driven Python code generation | `CodeGenerator`, `GeneratedCode` |
| `code_cache.py` | Approved-code cache (skip LLM on cache hit) | `CodeCache` (Protocol), `InMemoryCodeCache`, `CachedCode` |
| `envelope.py` | Request/response envelope helpers | `RequestEnvelope`, `ResponseEnvelope` |

### `runtime/llm/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports LLM types | |
| `base.py` | LLM backend protocol and message types | `LLMBackend` (Protocol), `LLMPrompt`, `LLMMessage`, `LLMResponse`, `LLMChunk`, `LLMUsage`, `ToolCall` |
| `mock.py` | Mock backend for testing (no network calls) | `MockBackend` |
| `anthropic.py` | Anthropic Claude backend | `AnthropicBackend` |
| `openai.py` | OpenAI GPT backend | `OpenAIBackend` |
| `gemini.py` | Google Gemini backend | `GeminiBackend` |
| `retry.py` | Exponential-backoff retry wrapper for transient LLM errors | `RetryConfig`, `with_retry` |

### `runtime/tools/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports tool types | |
| `base.py` | Tool protocol and definition types | `Tool` (Protocol), `ToolDefinition`, `ToolCapability` |
| `registry.py` | Tool registry (name -> Tool lookup) | `ToolRegistry` |
| `decorator.py` | `@tool` decorator for declaring tools from functions | `tool`, `DecoratedTool` |
| `database.py` | SQL database tool implementation | `DatabaseTool` |
| `http_client.py` | HTTP client tool | `HttpClientTool` |
| `cache.py` | Key-value cache tool | `CacheTool` |
| `queue.py` | Message queue tool | `QueueTool` |

### `runtime/memory/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports memory types | |
| `base.py` | Memory store protocol and record model | `MemoryStore` (Protocol), `MemoryRecord`, `MemoryKind`, `InMemoryMemoryStore` |
| `sqlite_store.py` | SQLite-backed persistent memory store | `SqliteMemoryStore` |

### `runtime/prompts/`

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports prompt builders | |
| `code_generation.py` | Prompt template for code generation | `build_code_generation_prompt` |
| `intent_parsing.py` | Prompt template for LLM-based intent parsing | `build_intent_parsing_prompt` |

---

## `mesh/` — Multi-Agent Orchestration

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports mesh types | `AgentMesh`, `MeshContext` |
| `mesh.py` | Multi-agent mesh container with `@role` and `@orchestrator` decorators | `AgentMesh` |
| `context.py` | Request-scoped inter-role call context with cycle detection and budget propagation | `MeshContext`, `MeshCycleError` |

---

## `application/` — Higher-Order Composition

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Package marker | |
| `pipeline.py` | Middleware-like stage composition for agent requests | `DynamicPipeline` |

---

## `ops/` — Operational Agents

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Package marker | |
| `base.py` | Abstract base class for operational agents | `OpsAgent` (ABC) |

---

## `cli/` — Command-Line Interface

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Package marker | |
| `main.py` | CLI entry point (typer-based) | `app` (typer app), `version` |
| `dev.py` | `agenticapi dev` — development server launcher | `dev` |
| `console.py` | `agenticapi console` — interactive REPL | `console` |
| `eval.py` | `agenticapi eval` — evaluation harness runner | `eval_cmd` |
| `replay.py` | `agenticapi replay` — audit trace replay | `replay` |

---

## `evaluation/` — Eval Harness

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Package marker | |
| `judges.py` | LLM-as-judge and rule-based evaluation judges | `Judge`, `ExactMatchJudge`, `LLMJudge` |
| `runner.py` | Batch evaluation runner | `EvalRunner`, `EvalResult` |

---

## `observability/` — OpenTelemetry Integration

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Re-exports observability primitives | |
| `tracing.py` | Tracer setup and no-op fallback | `configure_tracing`, `get_tracer`, `is_otel_available`, `reset_for_tests` |
| `metrics.py` | Counter/histogram recording + Prometheus exposition | `configure_metrics`, `record_request`, `record_policy_denial`, `record_llm_usage`, `record_tool_call`, `record_budget_block`, `render_prometheus_exposition` |
| `semconv.py` | Semantic convention constants (attribute names, span names) | `AgenticAPIAttributes`, `GenAIAttributes`, `SpanNames` |
| `propagation.py` | W3C traceparent propagation helpers | `extract_context_from_headers`, `inject_context_into_headers`, `headers_with_traceparent` |

---

## `testing/` — Test Utilities

| Module | Purpose | Key Exports |
|---|---|---|
| `__init__.py` | Package marker | |
| `fixtures.py` | Pytest fixtures for AgenticAPI testing | `agent_app`, `test_client` |
| `mocks.py` | Mock objects for harness, LLM, tools | `MockHarness`, `MockToolRegistry` |
| `assertions.py` | Custom assertion helpers | `assert_response_ok`, `assert_policy_denied` |
| `agent_test_case.py` | Base test case class for agent endpoint tests | `AgentTestCase` |
| `benchmark.py` | Performance benchmark utilities | `BenchmarkRunner` |
