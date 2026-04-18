# Current State

This document bridges the gap between:

- `PROJECT.md` (at the repo root): product vision and long-range architecture
- `CLAUDE.md` (at the repo root): contributor workflow, commands, and conventions
- The live implementation under `src/agenticapi/`

Read this before making large design changes. `PROJECT.md` is aspirational in several areas. This file is the reality check for what is wired today, what is partial, and where new work should start.

## How To Use This With The Other Docs

- Use `PROJECT.md` to understand the intended direction of the framework.
- Use `CLAUDE.md` to understand how to work in the repository safely.
- Use this file to determine whether a capability is already shipped, partially integrated, or still scaffolding.

## The Three Main Execution Styles

### 1. Direct handler execution

This is the most mature and most heavily used path.

- Triggered when no `llm` or `harness` is configured, or when an endpoint uses `autonomy_level="manual"`.
- The framework parses the request into `Intent` or `Intent[T]`, resolves `Depends()` dependencies, injects built-ins like `AgentContext`, `AgentTasks`, `UploadedFiles`, `HtmxHeaders`, and `AgentStream`, then calls the handler directly.
- This path powers the non-LLM examples, most response types, HTMX support, file handling, typed responses, and streaming handlers.

Primary files:

- `src/agenticapi/app.py`
- `src/agenticapi/dependencies/scanner.py`
- `src/agenticapi/dependencies/solver.py`
- `src/agenticapi/interface/intent.py`

### 2. Harnessed code-generation execution

This is the classic AgenticAPI path described in `PROJECT.md`.

- Triggered when both `llm` and `harness` are configured and the endpoint is not manual.
- The app first tries a tool-first path when tools are registered.
- If that path is not applicable, `CodeGenerator` produces Python and `HarnessEngine.execute()` runs the safety pipeline.

What the stock harness path currently does:

- Policy evaluation for code/data/resource/runtime policies
- Static AST analysis
- Approval workflow checks
- Sandbox execution
- Post-execution monitors and validators
- Audit recording

Primary files:

- `src/agenticapi/app.py`
- `src/agenticapi/runtime/code_generator.py`
- `src/agenticapi/harness/engine.py`
- `src/agenticapi/harness/policy/*`
- `src/agenticapi/harness/sandbox/*`

### 3. Streaming and replayable handler execution

Streaming is now a first-class interface path, not an afterthought.

- Handlers can accept `AgentStream` and emit structured events.
- SSE and NDJSON transports are both supported.
- Approval can pause a live stream and resume later.
- Completed streams can be replayed from the in-memory stream store.

Primary files:

- `src/agenticapi/interface/stream.py`
- `src/agenticapi/interface/stream_store.py`
- `src/agenticapi/interface/approval_registry.py`
- `src/agenticapi/interface/transports/sse.py`
- `src/agenticapi/interface/transports/ndjson.py`

## Fully Wired Today

These areas are implemented end-to-end in the current tree and are safe places to build on:

- `AgenticApp` request lifecycle, auth, sessions, OpenAPI, Swagger/ReDoc, and health/capabilities routes
- FastAPI-style dependency injection with caching, nested dependencies, overrides, and async-generator teardown
- Direct handler responses including `AgentResponse`, `FileResult`, `HTMLResult`, `PlainTextResult`, and raw Starlette responses
- Typed intent schema extraction at endpoint registration time
- Harness safety pipeline for generated code execution
- Streaming events, approval pause/resume, and replay routes
- Tool registry and `@tool` decorator
- In-memory audit plus persistent `SqliteAuditRecorder`
- Observability substrate: tracing, metrics helpers, propagation helpers, and optional `/metrics` route via `AgenticApp(metrics_url=...)`
- Extension packaging model, especially `extensions/agenticapi-claude-agent-sdk`
- PromptInjectionPolicy (B5): 10 regex rules, 5 categories, shadow mode, custom patterns
- PIIPolicy (B6): 6 detectors, Luhn-validated credit cards, detect/redact/block modes, `redact_pii()` utility
- Pre-LLM text policy invocation (Increment 9): `evaluate_intent_text()` hook fires before any LLM call or handler execution, automatically scans intent text through all policies that override the hook
- Agent memory (C1): `MemoryStore` protocol, `InMemoryMemoryStore`, `SqliteMemoryStore`, scope-based isolation, GDPR forget
- Code cache (C5): deterministic code reuse for repeated intents
- Eval harness (C6): `EvalSet`, `EvalCase`, `EvalRunner`, 5 built-in judges, YAML loading, `agenticapi eval` CLI

## Present But Not Fully Integrated

These are the most important "exists in code, but not fully wired through the stock path" areas.

### BudgetPolicy

`BudgetPolicy` is implemented and tested, but the stock `AgenticApp` plus `HarnessEngine` path does not automatically wrap every LLM call with:

- `BudgetPolicy.estimate_and_enforce(...)`
- `BudgetPolicy.record_actual(...)`

Important consequences:

- Budgeting works in the example and in custom orchestration where it is called explicitly.
- Adding `BudgetPolicy(...)` to `HarnessEngine(policies=[...])` is not, by itself, enough to guarantee stock request-path cost enforcement.
- Inside `PolicyEvaluator`, `BudgetPolicy.evaluate()` is intentionally a no-op compatibility stub.

Relevant files:

- `src/agenticapi/harness/policy/budget_policy.py`
- `examples/15_budget_policy/app.py`

### Typed intents with provider-native structured output

Typed intent schema extraction is wired, but provider-native structured-output enforcement is only fully exercised by `MockBackend` today.

- `IntentParser` forwards the schema through `LLMPrompt.response_schema`.
- `MockBackend` honors `response_schema` and returns deterministic structured payloads.
- The built-in Anthropic, OpenAI, and Gemini backends do not yet translate `response_schema` into each provider's native structured-output API.

This means:

- The typed-intent programming model is real.
- True provider-side schema enforcement is still partial.
- When using real provider backends, validation and fallback behavior matter more than the docs used to imply.

Relevant files:

- `src/agenticapi/interface/intent.py`
- `src/agenticapi/runtime/llm/base.py`
- `src/agenticapi/runtime/llm/mock.py`
- `src/agenticapi/runtime/llm/anthropic.py`
- `src/agenticapi/runtime/llm/openai.py`
- `src/agenticapi/runtime/llm/gemini.py`

### Native tool calling

The framework has a real tool-first execution path in `AgenticApp._try_tool_first_path()`, but built-in provider support is still partial.

- `LLMResponse.tool_calls` and `ToolCall` exist.
- `MockBackend` fully supports queued tool-call responses.
- `AgenticApp` can dispatch a single returned tool call straight into `HarnessEngine.call_tool()`.
- The built-in Anthropic and OpenAI backends pass `prompt.tools` through to the provider SDKs, but they do not yet normalize provider responses back into `LLMResponse.tool_calls` and `finish_reason`.
- The built-in Gemini backend does not currently translate `prompt.tools` into provider-native tool declarations.

Practical takeaway:

- The contract is defined.
- The stock tool-first path is production-shaped.
- Mock and custom backends exercise it fully today; the built-in provider adapters still need normalization work.

### Observability auto-instrumentation

Observability support exists, but automatic coverage is narrower than some older docs suggested.

Automatic today:

- Request count and request duration at the app boundary
- Intent-parsing LLM usage in `IntentParser`
- `/metrics` route registration when `metrics_url` is configured

Not universally automatic across all paths yet:

- Every policy denial
- Every budget block
- Every tool invocation
- Every tool-first or extension-driven LLM interaction
- Full cost attribution across all execution modes

Use the `record_*` helpers explicitly when building new paths.

## Areas That Are Mostly Scaffolding Or Early Surface Area

These modules exist and are useful, but they are not yet the center of the framework's shipped experience:

- `agenticapi.application.pipeline`
- `agenticapi.ops`
- `agenticapi.interface.a2a`

They are best treated as extension points and early architectural bets, not yet as the most stable core APIs.

### AgentMesh (newly shipped)

The `mesh/` package (`AgentMesh`, `MeshContext`) ships in-process multi-agent orchestration. Key characteristics:

- `@mesh.role(name=...)` registers both a role handler and a normal `/agent/{name}` endpoint.
- `@mesh.orchestrator(name=..., roles=[...])` registers orchestrator handlers that receive `MeshContext`.
- `MeshContext.call(role, payload)` performs cycle detection (raises `MeshCycleError`), budget enforcement (raises `BudgetExceeded`), and trace propagation (child trace IDs).
- In-process only — roles and orchestrators run in the same event loop. Cross-process mesh is a VISION.md Track 1 forward goal.
- Budget propagation is per-mesh-call only; integration with `BudgetPolicy` per-request scopes is future work.

### LLM retry (`runtime/llm/retry.py`)

`RetryConfig` + `with_retry()` provide async exponential-backoff with jitter for transient errors. Not yet wired into stock backends — available as a building block for custom backends or explicit caller use.

## Read Order For New Contributors

If you need to understand the implementation quickly, read in this order:

1. `src/agenticapi/app.py`
2. `src/agenticapi/interface/intent.py`
3. `src/agenticapi/dependencies/scanner.py`
4. `src/agenticapi/dependencies/solver.py`
5. `src/agenticapi/harness/engine.py`
6. `src/agenticapi/runtime/llm/base.py`
7. `src/agenticapi/interface/stream.py`
8. `src/agenticapi/harness/policy/budget_policy.py`
9. `src/agenticapi/observability/metrics.py`
10. `extensions/agenticapi-claude-agent-sdk/src/agenticapi_claude_agent_sdk/`

## Compatibility Rules For Ongoing Development

- Keep the direct handler path working without any LLM configured.
- Preserve optional-dependency behavior: missing SDKs must fail lazily and cleanly.
- Do not break `Depends()` overrides or async-generator teardown semantics.
- Preserve typed-intent backward compatibility: `intent.parameters` must remain usable even when `intent.payload` is typed.
- Keep streaming transports backward compatible once emitted event shapes are documented.
- Keep the Claude Agent SDK integration as a separate extension package rather than folding it into core.

## Scale (Increment 12)

- **141 Python modules**, ~26,725 lines of code
- **1,507 tests** (+38 in extensions), 32 examples, 86 `__all__` exports
- Phase A (control plane): complete
- Phase D (DX core): complete (Depends, Intent[T], response_model, @tool, route deps)
- Phase E (native function calling): complete — provider-specific tool format translation for Anthropic, OpenAI, Gemini; multi-turn `LLMMessage` with `tool_call_id` / `tool_calls`; integration tests with real APIs
- Phase F (streaming): core complete — AgentStream, SSE + NDJSON transports, approval pause/resume, AutonomyPolicy, StreamStore replay
- Phase B (safety): partial — B5 PromptInjectionPolicy, B6 PIIPolicy shipped
- Trace inspector: shipped — `/_trace` with search, diff, stats, export
- Harness MCP server: shipped — `HarnessMCPServer` exposing `@tool` functions with governance
- Phase C (agent intelligence): partial -- C1 MemoryStore, C5 CodeCache, C6 EvalHarness shipped
- Multi-agent: `AgentMesh` with `@mesh.role` / `@mesh.orchestrator`, `MeshContext.call()` with cycle detection and budget propagation

## Highest-Leverage Next Steps

If the goal is to move the codebase closer to the `PROJECT.md` vision, the best next steps are:

1. Wire `BudgetPolicy` into the stock LLM call path instead of leaving it as an explicit integration pattern.
2. Implement provider-native `response_schema` handling in the built-in Anthropic, OpenAI, and Gemini backends.
3. Normalize provider-native tool-call responses into `LLMResponse.tool_calls` and `finish_reason`.
4. Broaden automatic observability coverage for tool-first, streaming, budgeting, and extension-driven execution paths.
5. Decide which `application/`, `ops/`, and `a2a/` surfaces are graduating into the stable core and which remain experimental.
