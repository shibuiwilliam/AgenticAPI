# Module Reference — Complete Source Inventory

118 Python modules in `src/agenticapi/` organized by subpackage.

---

## Root-Level Modules

| File | Purpose |
|---|---|
| `__init__.py` | Public API surface — 73 symbols in `__all__` |
| `app.py` (~1,717 LOC) | Main ASGI application: endpoint registration, request dispatch, harness integration, pre-LLM text policy invocation |
| `routing.py` | `AgentRouter` — endpoint grouping with prefix/tags |
| `openapi.py` | OpenAPI 3.1.0 schema generation with typed `Intent[T]` request bodies (D7) and `response_model` schemas (D5) |
| `security.py` | Auth: `APIKeyHeader`, `APIKeyQuery`, `HTTPBearer`, `HTTPBasic`, `Authenticator`, `AuthUser` |
| `exceptions.py` | Exception hierarchy: `AgenticAPIError`, `PolicyViolation`, `BudgetExceeded`, `ApprovalRequired`, `SandboxViolation` |
| `types.py` | Enums: `AutonomyLevel`, `Severity`, `TraceLevel` |

## `interface/` — Request/Response Layer

| File | Purpose |
|---|---|
| `intent.py` (~686 LOC) | `Intent[T]` generic, `IntentParser`, `IntentScope`, `IntentAction` |
| `endpoint.py` | `AgentEndpointDef` (handler metadata, injection plan, response_model, streaming, autonomy) |
| `response.py` | `AgentResponse`, `FileResult`, `HTMLResult`, `PlainTextResult` |
| `stream.py` (~689 LOC) | `AgentStream` + 8 typed event types (Thought, ToolCall, Partial, Approval*, Final, Error, AutonomyChanged) |
| `stream_store.py` | `InMemoryStreamStore` for reconnect/resume (F7) |
| `approval_registry.py` | In-request HITL approval handle registry (F5) |
| `session.py` | `SessionManager` with in-memory state + TTL |
| `tasks.py` | `AgentTasks` — background tasks after response |
| `upload.py` | `UploadFile`, `UploadedFiles` for multipart |
| `htmx.py` | `HtmxHeaders` auto-injection + `htmx_response_headers()` |
| `transports/sse.py` | Server-Sent Events with 15s heartbeat |
| `transports/ndjson.py` | Newline-delimited JSON with 15s heartbeat |
| `compat/rest.py` | `RESTCompat` — agent endpoints as REST routes |
| `compat/mcp.py` | `MCPCompat` — agent endpoints as MCP tools |
| `compat/fastapi.py` | Mount AgenticApp inside FastAPI or vice versa |
| `a2a/protocol.py` | A2A message types (scaffolding) |
| `a2a/capability.py` | `CapabilityRegistry` |
| `a2a/trust.py` | `TrustScorer` |

## `dependencies/` — Dependency Injection

| File | Purpose |
|---|---|
| `depends.py` | `Depends()` marker + `Dependency` dataclass |
| `scanner.py` | `scan_handler()` → `InjectionPlan` (extracts `Intent[T]`, built-in injectables, `Depends()` chains) |
| `solver.py` | `solve()` + `invoke_handler()` (request-time resolution, caching, generator teardown) |

## `harness/` — Safety and Governance

| File | Purpose |
|---|---|
| `engine.py` (~515 LOC) | `HarnessEngine`: orchestrates policy eval → static analysis → approval → sandbox → monitors → validators → audit. Also `evaluate_intent_text()` (pre-LLM) and `call_tool()` (E4 tool-first) |

### `harness/policy/` — 11 Policy Classes

| Class | File | Purpose |
|---|---|---|
| `Policy` / `PolicyResult` | `base.py` | Base with `evaluate()`, `evaluate_intent_text()`, `evaluate_tool_call()` |
| `PolicyEvaluator` | `evaluator.py` | Aggregate all policies, raise `PolicyViolation` on denial |
| `CodePolicy` | `code_policy.py` | Forbidden imports, eval/exec |
| `DataPolicy` | `data_policy.py` | SQL table/column restrictions, DDL blocking |
| `ResourcePolicy` | `resource_policy.py` | CPU/memory/time limits |
| `RuntimePolicy` | `runtime_policy.py` | AST complexity limits |
| `BudgetPolicy` | `budget_policy.py` | Per-request/session/user/endpoint cost ceilings |
| `AutonomyPolicy` | `autonomy_policy.py` | Live escalation with `EscalateWhen` rules |
| `PromptInjectionPolicy` | `prompt_injection_policy.py` | 10 detection rules, shadow mode |
| `PIIPolicy` | `pii_policy.py` | 6 detectors (email, phone, SSN, CC+Luhn, IBAN, IPv4), 3 modes |
| `PricingRegistry` | `pricing.py` | Token-cost pricing table |

### `harness/sandbox/`

| File | Purpose |
|---|---|
| `base.py` | `SandboxRuntime` protocol |
| `process.py` | `ProcessSandbox`: subprocess isolation |
| `static_analysis.py` | AST walker for dangerous patterns |
| `monitors.py` | Runtime resource monitors |
| `validators.py` | Post-execution validation |

### `harness/approval/`

| File | Purpose |
|---|---|
| `workflow.py` | `ApprovalWorkflow` |
| `rules.py` | `ApprovalRule`, `EscalateWhen` |
| `notifiers.py` | `ApprovalNotifier`, `LogNotifier` |

### `harness/audit/`

| File | Purpose |
|---|---|
| `recorder.py` | `AuditRecorder`, `InMemoryAuditRecorder` |
| `sqlite_store.py` | `SqliteAuditRecorder` with `iter_since()` |
| `trace.py` | `ExecutionTrace` dataclass |
| `exporters.py` | JSON/CSV export |

## `runtime/` — Execution Infrastructure

| File | Purpose |
|---|---|
| `code_generator.py` | LLM-based code generation |
| `code_cache.py` | `InMemoryCodeCache` with LRU + TTL |
| `context.py` | `AgentContext` (request-scoped: tools, session, auth_user, memory) |

### `runtime/llm/`

| File | Purpose |
|---|---|
| `base.py` | `LLMBackend` protocol, `LLMPrompt`, `LLMResponse`, `ToolCall` |
| `anthropic.py` | `AnthropicBackend` (Claude) |
| `openai.py` | `OpenAIBackend` (GPT) |
| `gemini.py` | `GeminiBackend` (Gemini) |
| `mock.py` | `MockBackend` (deterministic) |
| `retry.py` | `RetryConfig` + `with_retry()` |

### `runtime/tools/`

| File | Purpose |
|---|---|
| `base.py` | `Tool` protocol, `ToolDefinition`, `ToolCapability` |
| `decorator.py` | `@tool` decorator |
| `registry.py` | `ToolRegistry` |
| `database.py`, `cache.py`, `http_client.py`, `queue.py` | Built-in tools |

### `runtime/memory/`

| File | Purpose |
|---|---|
| `base.py` | `MemoryStore` protocol, `MemoryRecord`, `MemoryKind` |
| `sqlite_store.py` | `SqliteMemoryStore` |

### `runtime/prompts/`

| File | Purpose |
|---|---|
| `intent_parsing.py` | System prompt for intent extraction |
| `code_generation.py` | System prompt + few-shot for codegen |

## `mesh/` — Multi-Agent Orchestration

| File | Purpose |
|---|---|
| `mesh.py` | `AgentMesh` with `@mesh.role`, `@mesh.orchestrator`, trace linkage, cycle detection |
| `context.py` | `MeshContext` for inter-agent calls with budget propagation |

## `evaluation/` — Continuous Assurance

| File | Purpose |
|---|---|
| `runner.py` | `EvalSet`, `EvalCase`, `EvalRunner`, `load_eval_set()` |
| `judges.py` | 5 built-in judges: ExactMatch, Contains, PydanticSchema, Latency, Cost |

## `observability/` — OpenTelemetry

| File | Purpose |
|---|---|
| `tracing.py` | Span tree with `gen_ai.*` semconv, no-op fallback |
| `metrics.py` | 9 canonical Prometheus metrics |
| `propagation.py` | W3C `traceparent` extraction/injection |
| `semconv.py` | Semantic convention constants |

## `cli/` — Command-Line Interface

| Subcommand | File | Purpose |
|---|---|---|
| `dev` | `dev.py` | Development server |
| `console` | `console.py` | Interactive REPL |
| `replay` | `replay.py` | Re-run audit trace |
| `eval` | `eval.py` | YAML eval set runner |
| `init` | `init.py` | Scaffold new project |
| `version` | `main.py` | Print version |

## `application/` — Dynamic Pipelines

`pipeline.py`: `DynamicPipeline`, `PipelineStage`, `PipelineResult`

## `ops/` — Operational Agents (scaffolding)

`base.py`: `OpsAgent` ABC

## `testing/` — Test Utilities

`agent_test_case.py`, `mocks.py`, `assertions.py`, `fixtures.py`, `benchmark.py`
