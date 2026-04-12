# Architecture — Implementation Deep Dive

Internal architecture for contributors. For the user-facing overview, see `docs/guides/architecture.md`.

---

## Six-Layer Module Dependency Graph

Higher layers import from lower; lateral imports within a layer are allowed. Backward imports are prohibited.

```
Layer 0: Foundation
    exceptions.py, types.py, _compat.py, params.py

Layer 1: Interface (HTTP boundary)
    interface/ — intent, response, stream, session, upload, htmx, tasks
    interface/transports/ — SSE, NDJSON wire formats
    interface/compat/ — REST, MCP, FastAPI interop
    interface/a2a/ — agent-to-agent protocol types (scaffolding)

Layer 2: Dependencies (injection)
    dependencies/ — Depends(), scanner, solver

Layer 3: Harness (safety + governance)
    harness/engine.py — orchestrator
    harness/policy/ — 11 policy classes + evaluator
    harness/sandbox/ — ProcessSandbox, static analysis, monitors, validators
    harness/approval/ — ApprovalWorkflow, rules, notifiers
    harness/audit/ — AuditRecorder, SqliteAuditRecorder, ExecutionTrace

Layer 4: Runtime (execution infrastructure)
    runtime/llm/ — 4 LLM backends + retry
    runtime/tools/ — @tool, ToolRegistry, built-in tools
    runtime/memory/ — MemoryStore, SqliteMemoryStore
    runtime/prompts/ — intent parsing + code generation templates
    runtime/code_generator.py, code_cache.py, context.py

Layer 5: Application + Orchestration
    application/pipeline.py — DynamicPipeline
    mesh/ — AgentMesh, MeshContext
    evaluation/ — EvalSet, EvalRunner, judges
    observability/ — tracing, metrics, propagation, semconv
    ops/ — OpsAgent base (scaffolding)
    cli/ — dev, console, replay, eval, init, version
    testing/ — fixtures, mocks, assertions, benchmarks

Top-level: app.py, routing.py, openapi.py, security.py, __init__.py
```

---

## Request Lifecycle — Four Execution Paths

Every request enters through `AgenticApp._handle_agent_request()` (app.py) and follows this sequence:

```
1. Extract JSON body → {"intent": "...", "session_id": "...", "context": {...}}
2. Authentication (if auth= configured) → AuthUser or 401
3. Session lookup/create (SessionManager)
4. IntentParser.parse(raw, session_context, schema=T) → Intent or Intent[T]
5. IntentScope check → 403 if denied
6. PRE-LLM TEXT POLICY SCAN (Increment 9):
     if harness is configured:
         harness.evaluate_intent_text(intent.raw, action, domain)
         → PromptInjectionPolicy.evaluate_intent_text(...)
         → PIIPolicy.evaluate_intent_text(...)
         → CodePolicy defaults to allow (not a text policy)
         → raises PolicyViolation → 403 if any policy denies
7. _execute_intent() branches:

   (a) HANDLER PATH (no LLM or autonomy_level="manual"):
       → DI solver resolves handler params (Depends, Intent, AgentContext, etc.)
       → handler(intent, context, ...) → AgentResponse
       → response_model validation (D5)
       → return 200

   (b) CODE-GENERATION PATH (LLM + harness + autonomy_level != "manual"):
       → BudgetPolicy.estimate_and_enforce (pre-call)
       → CodeCache lookup → if hit, skip LLM
       → CodeGenerator.generate(intent, tools) → generated Python code
       → PolicyEvaluator.evaluate(code=generated_code) → all policies
       → StaticAnalysis.check_code_safety(code) → AST walker
       → ApprovalCheck → if required, raise ApprovalRequired (202)
       → ProcessSandbox.execute(code) → isolated subprocess
       → Monitors (CPU, memory) → Validators (output safety)
       → BudgetPolicy.record_actual (post-call)
       → AuditRecorder.record(trace)
       → return AgentResponse

   (c) TOOL-FIRST PATH (E4: LLM picks a single tool):
       → LLMResponse.tool_calls has exactly one entry
       → HarnessEngine.call_tool(tool, arguments)
           → PolicyEvaluator.evaluate_tool_call(tool_name, args)
           → Tool.invoke(**args) → result
       → return AgentResponse (skips sandbox entirely — faster, cheaper)

   (d) STREAMING PATH (handler has AgentStream param):
       → AgentStream injected via DI scanner
       → Handler yields events lazily: ThoughtEvent, PartialEvent, etc.
       → Transport selected: SSE (F2) or NDJSON (F3)
       → AutonomyPolicy live escalation → signal evaluation mid-stream
       → stream.request_approval() → pause + auto-register resume endpoint
       → StreamStore persists events for reconnect (F7)
       → AuditRecorder.record(trace with stream_events)

8. Post-response: AgentTasks execute background work
```

---

## Pre-LLM Text Policy Invocation (Increment 9)

The `evaluate_intent_text()` hook fires at step 6 — before _execute_intent() branches. This means:

- **Both** the handler path (a) and the LLM path (b/c/d) get input scanning.
- The LLM never sees text that a policy would block.
- Policies that don't override `evaluate_intent_text()` (CodePolicy, DataPolicy, etc.) default to allow — zero impact on non-text policies.
- `PromptInjectionPolicy` and `PIIPolicy` both override the hook to delegate to their existing `evaluate(code=text)` method, so rules/modes/shadow work identically.

---

## DI Scanner Internals

`dependencies/scanner.py::scan_handler()` runs **once** at endpoint registration time and produces an `InjectionPlan` cached on `AgentEndpointDef.injection_plan`.

Built-in injectable types (detected by annotation, no `Depends()` needed):
- `Intent` / `Intent[T]` → `InjectionKind.INTENT` (extracts `intent_payload_schema` for D7 OpenAPI)
- `AgentContext` → `InjectionKind.CONTEXT`
- `AgentTasks` → `InjectionKind.AGENT_TASKS`
- `UploadedFiles` → `InjectionKind.UPLOADED_FILES`
- `HtmxHeaders` → `InjectionKind.HTMX_HEADERS`
- `AgentStream` → `InjectionKind.AGENT_STREAM`
- `MeshContext` → `InjectionKind.MESH_CONTEXT` (for mesh orchestrators)

Legacy positional fallback: unannotated `(intent, context)` handlers are detected and filled positionally.

---

## Mesh Orchestration

`mesh/mesh.py::AgentMesh` wraps `AgenticApp` and provides:
- `@mesh.role(name=..., description=...)` — registers both a regular `POST /agent/{name}` endpoint AND a mesh-internal role.
- `@mesh.orchestrator(name=..., roles=[...])` — the entry point clients call. Handler receives a `MeshContext`.
- `MeshContext.call(role, payload)` — in-process dispatch (LocalTransport). Resolves the role's handler, constructs an Intent, calls it directly. Budget and trace propagate via the context.
- Cycle detection: `MeshContext` tracks visited roles and raises `MeshCycleError` if a role calls itself (directly or transitively).

---

## Streaming Architecture

`interface/stream.py::AgentStream` is a request-scoped object injected via DI. The handler calls:
- `stream.emit(ThoughtEvent(...))` — emits an event to the transport
- `stream.request_approval(question, ...)` — pauses the stream, registers a resume endpoint, waits for operator approval
- `stream.report_signal(signal)` — feeds a signal to `AutonomyPolicy` for live escalation

Transport selection is automatic based on the `Accept` header:
- `text/event-stream` → SSE (`transports/sse.py`)
- `application/x-ndjson` → NDJSON (`transports/ndjson.py`)
- Default: SSE

`StreamStore` persists events for resume: `GET /agent/{name}/stream/{stream_id}?since=N`.

---

## Code Cache

`runtime/code_cache.py::InMemoryCodeCache` uses a deterministic SHA-256 key derived from `(intent_action, intent_domain, tool_names, policy_names)`. Cache hit skips the LLM call entirely. LRU eviction + TTL expiry.

---

## Evaluation Harness

`evaluation/runner.py::EvalRunner` loads a YAML `EvalSet`, sends each `EvalCase` to the live app, collects responses, fans out to judges. Exit code: 0 (all pass), 1 (some fail), 2 (error).

Five built-in judges: `ExactMatchJudge`, `ContainsJudge`, `PydanticSchemaJudge`, `LatencyJudge`, `CostJudge`. Custom judges implement the `EvalJudge` protocol.

CLI: `agenticapi eval --set evals/golden.yaml --app app:app --format text|json`
