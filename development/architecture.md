# Architecture — Implementation Deep Dive

This document covers the internal architecture of AgenticAPI at the implementation level. For the user-facing architecture overview, see `docs/guides/architecture.md`.

---

## Module Dependency Graph

The codebase is organized into six layers, each with controlled import boundaries. Higher layers import from lower layers; lateral imports within a layer are allowed.

```
src/agenticapi/
    __init__.py              <-- Public API surface (re-exports from all layers)
    app.py                   <-- ASGI application (imports from all layers)
    routing.py               <-- AgentRouter (parallel to app.py)
    exceptions.py            <-- Shared exception hierarchy (no internal deps)
    types.py                 <-- Shared enums: AutonomyLevel, Severity, TraceLevel
    _compat.py               <-- Python version check (side-effect import)
    params.py                <-- Query/Header parameter extraction
    openapi.py               <-- OpenAPI schema generation
    security.py              <-- Auth schemes + Authenticator

    interface/               <-- Layer 1: HTTP request/response types
        intent.py            <-- Intent, IntentParser, IntentScope, IntentAction
        endpoint.py          <-- AgentEndpointDef dataclass
        response.py          <-- AgentResponse, FileResult, HTMLResult, PlainTextResult
        tasks.py             <-- AgentTasks (background task runner)
        upload.py            <-- UploadFile, UploadedFiles
        session.py           <-- SessionManager, SessionState
        stream.py            <-- AgentStream, AgentEvent hierarchy, ApprovalHandle
        stream_store.py      <-- InMemoryStreamStore for reconnect/resume
        approval_registry.py <-- In-process pending approval handle registry
        htmx.py              <-- HtmxHeaders, htmx_response_headers
        transports/          <-- SSE (sse.py), NDJSON (ndjson.py) wire formats
        compat/              <-- MCP, REST, FastAPI compatibility layers
        a2a/                 <-- Agent-to-agent protocol (Phase 2 stub)

    dependencies/            <-- Layer 2: Dependency injection
        depends.py           <-- Depends() / Dependency sentinel
        scanner.py           <-- scan_handler() -> InjectionPlan (registration-time)
        solver.py            <-- solve() + invoke_handler() (request-time)

    harness/                 <-- Layer 3: Safety and governance
        engine.py            <-- HarnessEngine (orchestrator)
        policy/              <-- Policy implementations
        sandbox/             <-- ProcessSandbox, static_analysis
        approval/            <-- ApprovalWorkflow, rules, notifiers
        audit/               <-- AuditRecorder, ExecutionTrace, SqliteAuditRecorder

    runtime/                 <-- Layer 4: Execution infrastructure
        context.py           <-- AgentContext
        code_generator.py    <-- CodeGenerator (LLM -> Python code)
        code_cache.py        <-- InMemoryCodeCache for approved-code reuse
        envelope.py          <-- Request/response envelope helpers
        llm/                 <-- LLMBackend protocol + providers
        tools/               <-- Tool protocol, registry, decorator, built-ins
        memory/              <-- MemoryStore protocol + implementations
        prompts/             <-- Prompt templates for code gen + intent parsing

    mesh/                    <-- Layer 4b: Multi-agent orchestration
        mesh.py              <-- AgentMesh (@mesh.role, @mesh.orchestrator)
        context.py           <-- MeshContext (inter-role calls, cycle detection, budget)

    application/             <-- Layer 5: Higher-order composition
        pipeline.py          <-- DynamicPipeline (middleware-like stages)

    ops/                     <-- Layer 6: Operational agents
        base.py              <-- OpsAgent ABC

    cli/                     <-- CLI entry points (dev, console, eval, replay)
    evaluation/              <-- Eval harness (judges, runner)
    observability/           <-- OpenTelemetry tracing + metrics (optional)
    testing/                 <-- Test utilities (fixtures, mocks, assertions)
```

Import rule: `interface/` never imports from `harness/` or `runtime/`. The `app.py` module is the integration point that wires all layers together. `mesh/` sits between `runtime/` and `application/` — it imports from `interface/` and `runtime/` and is consumed by `app.py`.

---

## Request Lifecycle

### Non-streaming path (the default)

Every request enters through `app.py`'s ASGI handler, which Starlette routes to `_handle_agent_request`. Here is the exact sequence:

1. **HTTP parsing** (`_handle_agent_request`, ~line 860 in app.py)
   - Starlette parses the raw HTTP request.
   - JSON body is decoded; `intent` field extracted. For multipart, files are parsed into `UploadFile` objects.
   - Optional `session_id` extracted.

2. **Authentication** (~line 890)
   - If `endpoint_def.auth` (or app-level `self._auth`) is set, credentials are extracted via the scheme's `__call__` method and passed to the `verify` function.
   - Returns `AuthUser` or raises `AuthenticationError` (401).

3. **Traceparent propagation** (Phase A5)
   - `extract_context_from_headers` reads the `traceparent` header and restores the upstream OTel context so this request joins the distributed trace.

4. **`process_intent` entry** (~line 380)
   - Opens the root OTel span `agent.request`.
   - Gets or creates a `SessionState` via `SessionManager`.

5. **Intent parsing** (~line 460)
   - `IntentParser.parse(raw_request)` classifies the request into an `Intent` with `action` (StrEnum: read/write/delete/analyze/create/update/execute), `domain` (string), `params` (dict), and `confidence` (float).
   - When the handler declared `Intent[T]`, the `payload_schema` from the cached `InjectionPlan` is forwarded so the LLM constrains its output.

6. **Intent scope check** (~line 476)
   - If `endpoint_def.intent_scope` is set, `scope.matches(intent)` verifies the action/domain pair is allowed. Mismatch raises `PolicyViolation`.

7. **Context construction** (~line 499)
   - `AgentContext` is built with `trace_id`, `endpoint_name`, `session_id`, `user_id`, optional `memory` store, and a `metadata` dict carrying `auth_user`, `files`, and ASGI `scope`.

8. **`_execute_intent` dispatch** (~line 714)
   - If LLM + harness are configured and `autonomy_level != "manual"`: takes the **harness path** (`_execute_with_harness`).
   - Otherwise: takes the **direct handler path** (`_execute_handler_directly`).

9a. **Harness path** (`_execute_with_harness`, ~line 741)
   - **Tool-first path (Phase E4):** If a `ToolRegistry` is configured and the LLM supports native function calling, the LLM is asked for a structured tool call. If it returns exactly one unambiguous call, `HarnessEngine.call_tool` dispatches it directly (skipping code gen and sandbox).
   - **Code-generation path:** `CodeGenerator.generate()` asks the LLM to emit Python code. Optional code-cache lookup (Phase C5) can skip the LLM call.
   - **`HarnessEngine.execute()`**: Policy evaluation -> static analysis -> approval check -> sandbox execution -> monitors -> validators -> audit recording. See "Harness Pipeline" below.

9b. **Direct handler path** (`_execute_handler_directly`)
   - The DI solver resolves the handler's `InjectionPlan` (see "DI Scanner" below).
   - `invoke_handler(handler, resolved)` calls the handler with the resolved arguments.
   - The handler's return value is wrapped in `AgentResponse` (or returned as a raw Starlette `Response` for `FileResult`/`HTMLResult`/`PlainTextResult`).

10. **Session update** (~line 522)
    - The session's turn history is updated with the intent and a result summary.

11. **Background tasks** (~line 532)
    - If the handler injected `AgentTasks` and added callbacks, they execute now.

12. **Metrics recording** (Phase A2, ~line 536)
    - `record_request()` increments the request counter and records duration on the histogram.

### Streaming path (Phase F2/F3)

When `endpoint_def.streaming` is set (`"sse"` or `"ndjson"`), the request is routed to `_process_intent_streaming` instead of `process_intent`. Key differences:

1. An `AgentStream` is constructed with:
   - A unique `stream_id` (same as `trace_id`).
   - An approval handle factory from `ApprovalRegistry` (Phase F5).
   - The endpoint's `AutonomyPolicy` if any (Phase F6).
   - The `StreamStore` for reconnect persistence (Phase F7).

2. The handler is launched as a parallel `asyncio.Task` via the transport's `run_*_response` function.

3. The transport (`sse.py` or `ndjson.py`) consumes `stream.consume()` and renders each `AgentEvent` into the wire format, interleaving heartbeats.

4. When the handler completes, the transport emits a terminal `FinalEvent` (or `ErrorEvent`), then calls the `on_complete` callback which records the full event log into the audit trace (Phase F8).

---

## DI Scanner (`dependencies/scanner.py`)

The scanner runs **once per handler at registration time** and produces a cached `InjectionPlan`. This keeps the per-request solver fast.

### How `scan_handler` works

1. `inspect.signature(handler)` extracts parameter names and defaults.
2. `typing.get_type_hints(handler, include_extras=True)` resolves string annotations (supports `from __future__ import annotations`). Falls back to raw annotations on failure.
3. For each parameter, in declaration order:
   - **Priority 1:** If `default` is a `Dependency` instance (from `Depends(fn)`), classify as `InjectionKind.DEPENDS`.
   - **Priority 2:** Check the annotation against built-in types: `Intent`, `AgentContext`, `AgentTasks`, `UploadedFiles`, `HtmxHeaders`, `AgentStream`. Each has a `_is_*_annotation` helper that handles both the live type and string-form annotations.
   - **Priority 3:** For the first two unannotated parameters, assume legacy positional `(intent, context)` shape.
4. If `Intent[T]` is detected, `_extract_intent_payload_schema` pulls the Pydantic model `T` from the generic args and stores it on `InjectionPlan.intent_payload_schema`.

### Solver (`dependencies/solver.py`)

At request time, `solve(plan, ...)` fills in each parameter:

- `INTENT` -> the parsed `Intent` object.
- `CONTEXT` -> the `AgentContext`.
- `AGENT_TASKS` -> a fresh `AgentTasks()` instance.
- `UPLOADED_FILES` -> the file dict from the request.
- `HTMX_HEADERS` -> `HtmxHeaders.from_scope(scope)`.
- `AGENT_STREAM` -> the `AgentStream` (streaming endpoints only).
- `DEPENDS` -> recursively resolved via `_resolve_dependency`. Supports sync/async functions and sync/async generators (teardown via `AsyncExitStack`). Cached per-request when `use_cache=True`. Depth limit: 32.
- `POSITIONAL_LEGACY` -> intent/context filled positionally.

Route-level dependencies (`endpoint_def.dependencies`) are resolved first, for side effects only (their return values are discarded).

`app.dependency_overrides` is consulted during resolution, enabling test-time substitution.

---

## Harness Pipeline (`harness/engine.py`)

`HarnessEngine.execute()` runs the full safety pipeline:

```
1. PolicyEvaluator.evaluate()
   - Iterates all registered Policy instances.
   - Each returns PolicyResult(allowed, violations, warnings).
   - Raises PolicyViolation if any policy denies.

2. Static analysis (check_code_safety)
   - AST-walks the generated code.
   - Detects: denied imports, eval/exec, __import__, dangerous builtins, open().
   - Raises PolicyViolation if unsafe.

3. Approval check
   - If ApprovalWorkflow is configured, checks if the action/domain match any rule.
   - Raises ApprovalRequired (HTTP 202) if approval is needed.

4. Sandbox execution (ProcessSandbox)
   - Encodes code as base64.
   - Launches a subprocess with timeout.
   - Captures stdout, parses the JSON result envelope.

5. Post-execution monitors
   - Each ExecutionMonitor checks resource usage / output size.
   - Raises SandboxViolation on failure.

6. Post-execution validators
   - Each ResultValidator checks output correctness.
   - Raises SandboxViolation on failure.

7. Audit recording
   - AuditRecorder.record(trace) persists the ExecutionTrace.
```

The tool-first path (`HarnessEngine.call_tool`) skips steps 2-4 and 5-6, running only `evaluate_tool_call` (policy) and direct tool invocation.

---

## Streaming Architecture (`stream.py` -> `transports/`)

### Event Schema

All streaming events inherit from `AgentEvent` (Pydantic model) with a `kind` discriminator, `seq` (monotonic counter), and `timestamp` (UTC ISO-8601). Concrete types:

| Event class | `kind` | When emitted |
|---|---|---|
| `ThoughtEvent` | `thought` | Chain-of-thought chunks |
| `ToolCallStartedEvent` | `tool_call_started` | Before a tool invocation |
| `ToolCallCompletedEvent` | `tool_call_completed` | After a tool completes |
| `PartialResultEvent` | `partial_result` | Incremental result chunks |
| `ApprovalRequestedEvent` | `approval_requested` | Handler pauses for user input |
| `ApprovalResolvedEvent` | `approval_resolved` | User responded (or timeout) |
| `FinalEvent` | `final` | Terminal success |
| `ErrorEvent` | `error` | Terminal failure |
| `AutonomyChangedEvent` | `autonomy_changed` | Autonomy level escalated |

### Transport loop (SSE example)

1. `run_sse_response` creates an `asyncio.Task` for the handler.
2. The SSE generator (`_sse_event_iterator`) pulls from `stream.consume()` (an `asyncio.Queue`).
3. Each event is rendered as `event: <kind>\ndata: <json>\n\n`.
4. Heartbeat comments (`: keepalive\n\n`) are emitted every 15s to keep reverse proxies alive.
5. On client disconnect, the handler task is cancelled with a 2s grace period.

NDJSON uses the same pattern but renders one JSON line per event, with empty-line heartbeats.

### Approval flow (Phase F5)

1. Handler calls `await stream.request_approval(prompt=..., options=...)`.
2. Stream emits `ApprovalRequestedEvent` with an `approval_id` and `stream_id`.
3. An `ApprovalHandle` is created and registered in `ApprovalRegistry`.
4. The handler suspends on `handle.wait()` (an `asyncio.Event`).
5. External POST to `/agent/{name}/resume/{stream_id}` calls `handle.resolve(decision)`.
6. The handler resumes with the decision string.
7. Stream emits `ApprovalResolvedEvent`.

---

## Memory Subsystem

The memory store is wired at the application level:

```
AgenticApp(memory=store)
    -> self._memory = store
    -> AgentContext(memory=self._memory)  [per request]
    -> handler accesses context.memory.put() / .get() / .search() / .forget()
```

`MemoryStore` is a `Protocol` with four methods. Two implementations ship:
- `InMemoryMemoryStore` — dict-backed, for tests.
- `SqliteMemoryStore` — stdlib sqlite3, for persistent dev/prod use.

Each `MemoryRecord` carries a `scope` key (`"user:alice"`, `"session:abc"`, `"global"`), a logical `key`, a JSON-serialisable `value`, a `kind` (`episodic`/`semantic`/`procedural`), and a `timestamp`.

---

## Mesh Subsystem (`mesh/`)

The `AgentMesh` enables multi-agent orchestration within a single `AgenticApp`. It provides two decorators:

- `@mesh.role(name=...)` — registers a lightweight agent handler invokable via `MeshContext.call()`. Also registers the handler as a standalone `/agent/{name}` endpoint.
- `@mesh.orchestrator(name=..., roles=[...])` — registers a handler that receives a `MeshContext` for calling other roles.

### Call mechanics

```
@mesh.orchestrator("pipeline")
async def pipeline(intent, mesh_ctx):
    research = await mesh_ctx.call("researcher", intent.raw)
    summary  = await mesh_ctx.call("summarizer", research)
    return summary
```

`MeshContext.call()` performs:
1. **Cycle detection** — maintains a `call_stack` list; raises `MeshCycleError` if the same role appears twice.
2. **Budget enforcement** — if `budget_usd` is set on the orchestrator, checks `parent_budget_remaining_usd` before each call; raises `BudgetExceeded` on exhaustion.
3. **Trace propagation** — builds a child `trace_id` from `{parent_trace_id}:{role}:{uuid8}` for audit linkage.

### Integration with app.py

`AgentMesh.__init__` takes the `AgenticApp` and decorators call `app.agent_endpoint()` internally, so mesh roles and orchestrators appear as normal endpoints in `/docs`, `/capabilities`, and the OpenAPI schema.

### LLM retry (`runtime/llm/retry.py`)

`RetryConfig` + `with_retry()` provide exponential backoff with jitter for transient LLM provider errors (rate-limit, timeout, 5xx). Any backend can wrap its `generate()` call with `with_retry(fn, config)`. The retry loop is fully async.

---

## Data Flow Summary

```
HTTP POST /agent/{name}
    |
    v
Starlette routing -> _handle_agent_request
    |
    +-- Auth check (security.py)
    +-- extract_context_from_headers (observability/propagation.py)
    |
    v
process_intent (or _process_intent_streaming)
    |
    +-- SessionManager.get_or_create
    +-- IntentParser.parse -> Intent
    +-- IntentScope.matches check
    +-- AgentContext construction (memory wired here)
    |
    +-- [streaming] -> AgentStream + transport (SSE/NDJSON)
    +-- [non-streaming] -> _execute_intent
         |
         +-- [LLM + harness] -> _execute_with_harness
         |       |
         |       +-- [tool-first] -> HarnessEngine.call_tool
         |       +-- [code-gen]  -> CodeGenerator -> HarnessEngine.execute
         |
         +-- [direct handler] -> DI solve -> invoke_handler
    |
    v
AgentResponse (JSON) or Starlette Response (file/HTML/streaming)
```
