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
    workflow/ — AgentWorkflow, WorkflowState, WorkflowStore
    evaluation/ — EvalSet, EvalRunner, judges
    observability/ — tracing, metrics, propagation, semconv
    playground/ — /_playground backend + UI
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
       → CodeGenerator.generate(intent, tools) → LLM call with retry (RetryConfig)
         → LLMPrompt carries tool_choice ("auto"/"required"/"none"/specific)
         → On transient error (429, 5xx, timeout): exponential backoff + jitter
         → result: generated Python code or ToolCall objects
       → PolicyEvaluator.evaluate(code=generated_code) → all policies
       → StaticAnalysis.check_code_safety(code) → AST walker
       → ApprovalCheck → if required, raise ApprovalRequired (202)
       → ProcessSandbox.execute(code) → isolated subprocess
       → Monitors (CPU, memory) → Validators (output safety)
       → BudgetPolicy.record_actual (post-call)
       → AuditRecorder.record(trace)
       → return AgentResponse

   (c) AGENTIC LOOP PATH (LLM + harness + tools registered):
       → run_agentic_loop() — multi-turn ReAct pattern
       → Iteration: LLM.generate(prompt with tools)
         → if finish_reason="tool_calls":
             for each ToolCall:
               → HarnessEngine.call_tool(tool, arguments) — policy + audit
               → Append tool result as LLMMessage(role="tool") to conversation
             → Send updated conversation back to LLM
         → if finish_reason="stop" or max_iterations:
             → Return LoopResult(final_text, tool_calls_made, iterations)
       → BudgetPolicy tracked per LLM call (estimate + reconcile)
       → OTEL span per iteration
       → Falls back to code-generation path (b) on failure

   (d) WORKFLOW PATH (endpoint has workflow= configured):
       → AgentWorkflow.run(state, context, harness, tools)
       → Steps execute sequentially: step_func(state, WorkflowContext) → next_step_name
       → Conditional branching: step returns str (next step) or list[str] (parallel)
       → Checkpoints: step with checkpoint=True pauses workflow, returns partial state
       → Resume: POST /agent/{name}?workflow_id=xxx loads state and continues
       → WorkflowContext.call_tool() goes through HarnessEngine.call_tool()
       → return WorkflowResult wrapped in AgentResponse

   (e) STREAMING PATH (handler has AgentStream param):
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

## LLM Retry and Native Function Calling

All four LLM backends support native function calling and transient-error retry:

**Retry** (`runtime/llm/retry.py`): `RetryConfig` + `with_retry()` async wrapper. Each backend constructs a default `RetryConfig` targeting its provider's transient exceptions:
- Anthropic: `RateLimitError`, `APITimeoutError`, `InternalServerError`
- OpenAI: `RateLimitError`, `APITimeoutError`
- Gemini: `ResourceExhausted`, `ServiceUnavailable`

Backoff: exponential with configurable jitter, base delay, max delay, and max retries.

**Native function calling**: Every real backend (not just `MockBackend`) now:
1. Converts `LLMPrompt.tools` into the provider's native format.
2. Maps `LLMPrompt.tool_choice` (`"auto"` / `"required"` / `"none"` / `{"type": "tool", "name": "..."}`) into provider-specific API parameters.
3. Parses provider responses into `ToolCall(id, name, arguments)` objects on `LLMResponse.tool_calls`.
4. Maps provider stop reasons to a normalized `LLMResponse.finish_reason` (`"stop"`, `"tool_calls"`, `"length"`, `"content_filter"`).

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

---

## Agentic Loop (ReAct Pattern)

`runtime/loop.py` implements the multi-turn tool-calling loop that makes AgenticAPI genuinely agentic. The loop supersedes the single-shot E4 tool-first path.

**Core flow:**

```
run_agentic_loop(llm, tools, harness, prompt, config) → LoopResult

  for iteration in 1..max_iterations:
    response = llm.generate(prompt_with_tools)
    if no tool_calls → return final_text
    for each tool_call:
      result = harness.call_tool(tool, args)   # policy + audit
      append LLMMessage(role="tool", content=result) to conversation
    send updated conversation back to LLM
```

**Key design decisions:**
- Every tool call goes through `HarnessEngine.call_tool()` — no shortcuts.
- Budget tracking per LLM call via `BudgetPolicy.estimate_and_enforce()` / `record_actual()`.
- Unknown tools get an error message appended as a tool result, letting the LLM recover.
- Tool failures raise `ToolError`; policy violations raise `PolicyViolation` — both halt the loop.
- Streaming variant `run_agentic_loop_streaming()` emits `ToolCallStartedEvent`, `ToolResultEvent`, `ThoughtEvent`, `FinalEvent` through `AgentStream`.
- `LoopConfig(max_iterations=N)` is configurable per endpoint via `@app.agent_endpoint(loop_config=...)`.
- The loop is wired into `AgenticApp._run_agentic_loop()` which is called from `_execute_with_harness()` when tools are registered.

---

## Workflow Engine

`workflow/` implements declarative multi-step agent workflows with typed state.

**Architecture:**

```
AgentWorkflow[S](name, state_class)
  @workflow.step("name", checkpoint=False, max_retries=0)
  async def step(state: S, context: WorkflowContext) -> str | list[str] | None:
      ...  # return next step name, parallel list, or None to end

  workflow.run(initial_state, context, harness, tools, llm) → WorkflowResult[S]
```

**Key components:**
- `WorkflowState` — Pydantic `BaseModel` subclass carrying typed fields. The framework manages `wf_current_step`, `wf_completed_steps`, `wf_iteration_count`.
- `AgentWorkflow[S]` — Generic workflow with `@step()` decorator for registering steps.
- `WorkflowContext` — Provides `call_tool()`, `llm_generate()`, `trace_id`, `budget_remaining_usd` to step functions.
- `WorkflowResult[S]` — Final state, steps executed, duration, checkpoint info.
- `WorkflowStore` — Protocol for persisting checkpoint state. `InMemoryWorkflowStore` and `SqliteWorkflowStore` shipped.

**Routing logic:**
- Step returns `str` → sequential: execute the named step next.
- Step returns `list[str]` → parallel: `asyncio.gather()` all named steps.
- Step returns `None` → workflow complete.
- Step with `checkpoint=True` → persist state, return paused result.

**App integration:** `@app.agent_endpoint(workflow=my_workflow)` bypasses the handler and runs the workflow engine via `_execute_workflow()`.

---

## Agent Playground

`playground/` provides a self-hosted, zero-dependency agent debugger UI at `/_playground`.

**Backend API (playground/routes.py):**
- `GET /_playground/api/endpoints` — list registered endpoints with metadata (tools, policies, auth, streaming, loop config).
- `GET /_playground/api/traces` — list recent traces from `AuditRecorder`.
- `GET /_playground/api/traces/{id}` — single trace with timeline.
- `POST /_playground/api/chat` — dispatch to agent via `app.process_intent()`.
- `GET /_playground` — serve the HTML/JS/CSS UI.

**Frontend (inline HTML, no build step):**
- Three-panel layout: Agent Chat | Execution Trace | Trace History.
- Chat uses `fetch()` to POST to `/api/chat`, renders responses.
- Trace History lists recent traces; click loads detail into the trace viewer.
- Timeline renders events with color-coded border (green=pass, red=error, purple=tool, blue=LLM).
- Dark theme, monospace, responsive.

**Mounting:** `AgenticApp(playground_url="/_playground")`. Disabled by default (`None`). Routes are stored in `app._playground_routes` and included in `_build_starlette()`.

---

## Trace Inspector

`trace_inspector/` provides a self-hosted trace inspection UI at `/_trace` for searching, diffing, and exporting execution traces.

**Backend API (trace_inspector/routes.py):**
- `GET /_trace/api/search` — search traces with filters (endpoint, status, tool, date range, cost range). Returns paginated summaries.
- `GET /_trace/api/traces/{id}` — full trace detail with timeline.
- `GET /_trace/api/diff?a={id}&b={id}` — structural diff of two traces. Reports changed fields.
- `GET /_trace/api/stats` — aggregate cost/status/tool statistics across traces.
- `GET /_trace/api/export/{id}` — JSON compliance report with `Content-Disposition: attachment`.
- `GET /_trace` — serve the HTML/JS/CSS UI.

**Frontend (inline HTML, no build step):**
- Four-tab layout: Search | Detail | Diff | Stats.
- Search: filter bar + results table with status/cost/duration columns.
- Detail: timeline waterfall with color-coded entries, LLM usage, export button.
- Diff: side-by-side comparison of two traces.
- Stats: card grid with total traces, cost, per-endpoint and per-tool breakdown.
- All user-controlled data HTML-escaped via `esc()` to prevent XSS.

**Data model:** `_trace_to_summary()` extracts tool names from `stream_events` and `mcp:` endpoint prefixes. `_aggregate_stats()` produces `by_endpoint`, `by_status`, and `by_tool` breakdowns.

**Mounting:** `AgenticApp(trace_url="/_trace")`. Disabled by default. Routes stored in `app._trace_inspector_routes`.

---

## Harness-Governed MCP Tool Server

`mcp_tools/` exposes registered `@tool` functions as MCP tools with full harness governance.

**HarnessMCPServer (mcp_tools/server.py):**
- Iterates `app._tools.get_definitions()` to build MCP tool list.
- For each tool call from an MCP client: `HarnessEngine.call_tool()` with policy evaluation, audit recording, and JSON result serialization.
- Mounted as an ASGI sub-app via `starlette.routing.Mount` with lifespan management for `FastMCP.SessionManager`.
- Requires `pip install agentharnessapi[mcp]`.

**Audit integration:** Tool calls use endpoint_name `"mcp:{tool_name}"` so traces are distinguishable from normal endpoint requests. The trace inspector's tool filter can find MCP-originated calls.

**Mounting:** `HarnessMCPServer(app, path="/mcp/tools")` — called by the application, not by the framework constructor. This is explicit so apps that don't use MCP pay nothing.

---

## Provider Tool Format Translation

Each LLM backend translates between the framework's generic tool format and the provider's native wire format. This is handled in `_build_request_kwargs()` (or `_build_request_params()` for Gemini).

**Generic format (from `_tools_to_llm_format()` in loop.py):**
```json
{"name": "calc", "description": "...", "parameters": {"type": "object", ...}}
```

**Anthropic translation (`_normalize_tool()`):**
- `parameters` → `input_schema`
- Assistant messages with `tool_calls` → content blocks with `tool_use` entries
- Tool result messages → `user` role with `tool_result` content blocks keyed by `tool_use_id`

**OpenAI translation (`_normalize_tool()`):**
- Wraps in `{"type": "function", "function": {"name", "description", "parameters"}}`
- Assistant messages with `tool_calls` → `tool_calls` array with `function` objects (arguments JSON-encoded)
- Tool result messages → `tool` role with `tool_call_id`

**Gemini translation (`_convert_tools()`, `_resolve_tool_name()`):**
- Produces `FunctionDeclaration` objects
- Assistant messages with `tool_calls` → `function_call` parts on `model` messages
- Tool result messages → `function_response` parts on `user` messages; `_resolve_tool_name()` walks backward through the conversation to find the actual function name (not the call ID)

**Multi-turn message model:** `LLMMessage` carries two optional fields:
- `tool_call_id: str | None` — on `role="tool"` messages, links back to the originating tool call
- `tool_calls: list[ToolCall] | None` — on `role="assistant"` messages, preserves the full tool call structure for provider-specific formatting

Both the sync (`run_agentic_loop`) and streaming (`run_agentic_loop_streaming`) variants populate these fields.
