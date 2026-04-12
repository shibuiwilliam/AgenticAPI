# AgenticAPI — Roadmap

> **Single source of execution truth.** Status as of **Increment 9** (2026-04-12).
> Every `IMPLEMENTATION_LOG.md` entry must update this file in the same commit.
> For product vision see [`PROJECT.md`](PROJECT.md). For speculative tracks see
> [`VISION.md`](VISION.md). For the append-only shipped-work log see
> [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md).

---

## At a glance

| Plane | Purpose | Status |
|---|---|---|
| **D — Typed handlers + DI** | FastAPI-shaped handler ergonomics: `Depends`, `Intent[T]`, `response_model`, route-level dependencies | **Core complete** (D1–D7 done; D8 deferred) |
| **E — Tools as functions** | `@tool`-decorated async functions → JSON Schemas → native LLM function calls → tool-first execution | **Core shipped** (E1–E4 done; E5–E8 deferred) |
| **F — Streaming lifecycle** | `AgentStream`, SSE / NDJSON transports, progressive autonomy, in-request human-in-the-loop, resumable streams | **Effectively complete** (F1–F3, F5–F8 done; F4 WebSocket optional) |
| **A — Control plane** | OTEL tracing, Prometheus metrics, persistent audit, cost budget, trace propagation, replay CLI | **Complete** (A1–A6 all shipped) |
| **B — Safety plane** | Prompt-injection, PII redaction, pre-LLM input scanning, output schema, container sandbox hardening | **Partial** (B5, B6, pre-LLM invocation shipped; B1–B4, B7–B8 deferred / pending) |
| **C — Learning plane** | Agent memory, approved-code cache, eval harness, replay-from-audit | **Core shipped** (C1, C5, C6 done; C2–C4, C7–C8 pending) |

**Code stats as of Increment 9:**

- 118 Python modules in `src/agenticapi/` · ~21,944 LOC
- 1,304 main tests + 38 extension tests · mypy `--strict` clean · ruff format + lint clean · mkdocs `--strict` clean
- 27 example apps (`examples/01_hello_agent` through `26_dynamic_pipeline`)
- 75 symbols in `agenticapi.__all__`
- 1 extension (`agenticapi-claude-agent-sdk` v0.1.0)

---

## Shipped

Every shipped task below links to the [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md)
entry where it landed. Implementation blueprints for upcoming tasks live in
[`CLAUDE.md`](CLAUDE.md) > Implementation Blueprints. Strategic priorities are in
[`PROJECT.md`](PROJECT.md) > Immediate Strategic Priorities.

### Phase D — Typed handlers + dependency injection

| Task | Description | Increment | Public API |
|---|---|---|---|
| **D1** ✅ | `Depends()` + handler signature scanner + DAG solver + request-scoped cache + `app.dependency_overrides` | [Increment 1](IMPLEMENTATION_LOG.md) | `Depends`, `Dependency` |
| **D2** ✅ | Request-scoped dependency cache (folded into D1) | Increment 1 | — |
| **D3** ✅ | `app.dependency_overrides` for tests (folded into D1) | Increment 1 | `AgenticApp.dependency_overrides` |
| **D4** ✅ | `Intent[T]` generic with Pydantic payload + structured-output constraint on LLM backends | [Increment 2](IMPLEMENTATION_LOG.md) | `Intent[T]`, `IntentParser(schema=...)` |
| **D5** ✅ | `response_model=` on `@agent_endpoint` with per-endpoint OpenAPI schemas | Increment 1 | `agent_endpoint(response_model=...)` |
| **D6** ✅ | Route-level `dependencies=[…]` for cross-cutting concerns (auth, rate limit) | Increment 2 | `agent_endpoint(dependencies=[...])` |
| **D7** ✅ | Schema-driven OpenAPI output — `response_model` (Inc 1) and per-endpoint `Intent[T]` request bodies with `$ref` to the payload schema (Inc 8) | [Increment 8](IMPLEMENTATION_LOG.md) | — |
| **D8** ⏸ | Migration guide + backward-compat shim | Deferred — all legacy handlers already work unchanged | — |

### Phase E — Tools as type-hinted Python functions

| Task | Description | Increment | Public API |
|---|---|---|---|
| **E1** ✅ | `@tool` decorator deriving JSON Schema from type hints + Pydantic validation of kwargs | [Increment 1](IMPLEMENTATION_LOG.md) | `@tool` |
| **E2** ✅ | `ToolRegistry.register(plain_function)` auto-wraps with `@tool` (folded into E1) | Increment 1 | `ToolRegistry.register` |
| **E3** ✅ | Native function-calling representation (`ToolCall` on `LLMResponse`, `finish_reason`) via MockBackend | [Increment 3](IMPLEMENTATION_LOG.md) | `ToolCall`, `LLMResponse.tool_calls` |
| **E4** ✅ | Tool-first execution path in `HarnessEngine.call_tool` — skip code-gen when the LLM picks a single tool | [Increment 6](IMPLEMENTATION_LOG.md) | `HarnessEngine.call_tool`, `Policy.evaluate_tool_call` |
| **E5** ⏸ | Typed tool composition (`ToolGraph` type-safe chaining) | Deferred | — |
| **E6** ⏸ | Per-tool policy enforcement for `DataPolicy` on tool arguments | Deferred (hook exists from E4) | — |
| **E7** ⏸ | Unified MCP / REST / OpenAPI auto-exposure from one `@tool` | Deferred | — |
| **E8** ⏸ | Per-provider native function calling (Anthropic, OpenAI, Gemini round-trip) | Deferred (MockBackend proven; real providers pending) | — |

### Phase F — Streaming lifecycle + progressive autonomy + in-request HITL

| Task | Description | Increment | Public API |
|---|---|---|---|
| **F1** ✅ | `AgentStream` handler parameter + 8 typed event types with monotonic seq + timestamps | [Increment 4](IMPLEMENTATION_LOG.md) | `AgentStream`, `AgentEvent`, `ThoughtEvent`, `ToolCallEvent`, `PartialEvent`, `ApprovalRequestEvent`, `ApprovalResolvedEvent`, `FinalEvent`, `ErrorEvent`, `AutonomyChangedEvent` |
| **F2** ✅ | SSE transport (`text/event-stream`) with heartbeats and cancel-on-disconnect | Increment 4 | auto-registered when handler has `AgentStream` param |
| **F3** ✅ | NDJSON transport (`application/x-ndjson`) for CLI consumers | [Increment 5](IMPLEMENTATION_LOG.md) | content-negotiated |
| **F4** ⏸ | WebSocket transport | Optional / deferred — SSE + NDJSON cover the standard cases | — |
| **F5** ✅ | `stream.request_approval()` in-request HITL + resume endpoint (`/agent/{name}/resume/{stream_id}`) + `ApprovalRegistry` | Increment 4 | `AgentStream.request_approval`, `ApprovalRegistry` |
| **F6** ✅ | `AutonomyPolicy` with `EscalateWhen` rules + live escalation during a stream + `AutonomyChangedEvent` | [Increment 5](IMPLEMENTATION_LOG.md) | `AutonomyPolicy`, `AutonomySignal`, `EscalateWhen` |
| **F7** ✅ | Resumable streams via `StreamStore` (`/agent/{name}/stream/{stream_id}?since=N`) | Increment 5 | `StreamStore`, `InMemoryStreamStore` |
| **F8** ✅ | Audit integration — `ExecutionTrace.stream_events` records full lifecycle | Increment 4 | `ExecutionTrace.stream_events` |

### Phase A — Control plane (observability, cost, propagation)

**Complete.** All 6 tasks shipped.

| Task | Description | Increment | Public API |
|---|---|---|---|
| **A1** ✅ | OTEL-native root + child spans with `gen_ai.*` semconv across the full pipeline (no-op when OTEL absent) | [Increment 2](IMPLEMENTATION_LOG.md) | `agenticapi.observability.tracing`, `configure_tracing()` |
| **A2** ✅ | Prometheus `/metrics` endpoint exposing 9 canonical agent metrics | Increment 2 | `agenticapi.observability.metrics`, `configure_metrics()` |
| **A3** ✅ | `SqliteAuditRecorder` (stdlib sqlite3 + `asyncio.to_thread`) with `iter_since()` for eval replay | [Increment 3](IMPLEMENTATION_LOG.md) | `SqliteAuditRecorder` |
| **A4** ✅ | `BudgetPolicy` + `PricingRegistry` + `BudgetExceeded` → HTTP 402 | [Increment 1](IMPLEMENTATION_LOG.md) | `BudgetPolicy`, `PricingRegistry`, `BudgetExceeded` |
| **A5** ✅ | W3C `traceparent` propagation (incoming → parent span; outgoing helper) | Increment 3 | `agenticapi.observability.propagation` |
| **A6** ✅ | Replay primitive + `agenticapi replay` CLI re-running audit traces through the live pipeline | [Increment 6](IMPLEMENTATION_LOG.md) | `agenticapi replay <trace_id>` |

### Phase B — Safety plane (isolation + semantic guardrails)

| Task | Description | Status | Notes |
|---|---|---|---|
| **B1** ⏸ | `ContainerSandbox` (Docker / Podman / gVisor) | Deferred | `ProcessSandbox` + AST policies cover the common case; unblock on customer demand |
| **B2** ⏸ | `NsjailSandbox` (Linux-only, optional) | Deferred | Deferred with B1 |
| **B3** ⏸ | Declarative capability grants | Deferred | Deferred with B1 |
| **B4** ⏸ | Actually enforce `ResourcePolicy` (currently advisory-only) | Deferred | Deferred with B1 |
| **B5** ✅ | `PromptInjectionPolicy` with 10 built-in detection rules + `disabled_categories=` + `extra_patterns=` + shadow mode | [Increment 7](IMPLEMENTATION_LOG.md) | `PromptInjectionPolicy` |
| **B6** ✅ | `PIIPolicy` — detect / redact / block for email, phone, SSN, credit card (Luhn-validated), IBAN, IPv4 + `disabled_detectors` + `extra_patterns` + `evaluate_tool_call` hook + standalone `redact_pii()` utility | [Increment 8](IMPLEMENTATION_LOG.md) | `PIIPolicy`, `PIIHit`, `redact_pii` |
| **B7** ⏸ | `OutputSchemaPolicy` — enforce Pydantic schema on agent output | Pending | Available on demand |
| **B8** ⏸ | Adversarial test suite for sandbox escape | Pending | Depends on B1 |

### Phase C — Learning plane (memory + evaluation + feedback loop)

| Task | Description | Increment | Public API |
|---|---|---|---|
| **C1** ✅ | `MemoryStore` protocol + `InMemoryMemoryStore` + `SqliteMemoryStore` + `MemoryRecord` + `MemoryKind` (episodic / semantic / procedural) + `AgentContext.memory` | [Increment 6](IMPLEMENTATION_LOG.md) | `MemoryStore`, `InMemoryMemoryStore`, `SqliteMemoryStore`, `MemoryRecord`, `MemoryKind` |
| **C2** ⏸ | `SemanticMemory` + embedding-based retrieval + `PgVectorStore` | Pending | Next-iteration target |
| **C3** ⏸ | `MemoryPolicy` — retention, PII redaction, forget-on-request | Pending | Next-iteration target |
| **C4** ⏸ | Prompt-caching integration (Anthropic ephemeral, OpenAI prefix) | Pending | Ship on demand |
| **C5** ✅ | Approved-code cache with deterministic SHA-256 key + LRU + TTL + `agenticapi_code_cache_*` metrics | [Increment 7](IMPLEMENTATION_LOG.md) | `CodeCache`, `InMemoryCodeCache`, `CachedCode` |
| **C6** ✅ | `EvalSet` + 5 built-in judges (exact, contains, latency, cost, schema) + `agenticapi eval` CLI | Increment 7 | `agenticapi.evaluation`, `agenticapi eval` |
| **C7** ⏸ | Replay-from-audit eval mode (`--from-audit --since 7d --sample 100`) | Pending | Auto-generate eval cases from production traffic |
| **C8** ⏸ | GitHub Action template wrapping `agenticapi eval` | Pending | Depends on C6 (ready to implement) |

---

## Active — candidates for the next increment

No commitments yet; these are the highest-leverage gaps given current shipped work:

1. **C2 — Semantic memory + embeddings + `PgVectorStore`.** C1 laid the
   protocol foundation. Semantic retrieval is the most requested follow-on
   and unblocks RAG patterns inside agent handlers.
2. **C7 — Replay-from-audit eval mode.** A6 (replay CLI) + A3 (`iter_since`)
   + C6 (EvalSet) are all shipped. C7 is the "close the loop" task that
   lets operators auto-generate eval cases from production traffic. Small
   surface area, high leverage.
3. **E8 — Native function calling for real providers.** The representation
   exists (E3) but `AnthropicBackend`, `OpenAIBackend`, and `GeminiBackend`
   don't yet emit provider-native `tools=` / `tool_choice=` payloads.
   Unblocks production use of E4 tool-first path beyond `MockBackend`.
4. **B7 — `OutputSchemaPolicy`.** Low-effort policy addition that enforces
   a Pydantic schema on agent output before serialization. Follows B5 /
   B6's shape and composes with D5 `response_model`.
5. **B7 — `OutputSchemaPolicy`.** Enforce Pydantic schema on agent output
   before serialization. Follows B5/B6's shape. Low-effort, high-value
   for regulated workloads. Composes with D5 `response_model`.

---

## Deferred

Explicitly parked with reason; not dropped, just not prioritised.

| Task | Reason |
|---|---|
| **B1–B4** (container sandbox hardening) | `ProcessSandbox` + AST policies cover the majority of production usage. Container / nsjail / seccomp work is unlocked on the first customer deployment that needs it. See [`VISION.md`](VISION.md) > Phase T for the "Hardened Trust" re-opening plan. |
| **F4** (WebSocket transport) | SSE (F2) and NDJSON (F3) together cover browser, CLI, and most server-to-server use cases. Revisit if a customer specifically needs bidirectional streaming. |
| **E5** (typed tool composition) | LLM planning currently returns one tool per turn; multi-step composition is speculative until E8 ships and we see real multi-tool plans. |
| **E6** (per-tool policy enforcement) | `Policy.evaluate_tool_call` hook exists (E4). Only `DataPolicy` would need the enforcement, and existing tool code is already narrow enough that hand-written validation is cheaper than the indirection. |
| **E7** (unified MCP / REST / OpenAPI auto-exposure) | The three existing exposure mechanisms (`@app.agent_endpoint(enable_mcp=True)`, `RESTCompat`, `openapi.py`) are fine; auto-discovering `@tool`s across them is a convenience, not a capability. |
| **D8** (migration guide) | All legacy `(intent, context)` handlers work unchanged under the new DI scanner; the guide has no audience. |

---

## Superseded — items from the original `PROJECT.md` Phase 2 roadmap

These items appeared in the original `PROJECT.md` Phase 2 roadmap (still
readable in [`VISION.md`](VISION.md) > Historical Appendix). Most have been
superseded by the D/E/F/A/C planes that shipped in Increments 1–7; a few are
genuinely still pending.

| Original item | Current status | Replaced / covered by |
|---|---|---|
| A2A server/client | **Partial** — `interface/a2a/{protocol,capability,trust}.py` types exist; full server/client/discovery pending | — |
| Service discovery | Pending | — |
| AdaptiveDataAccess | Pending | — |
| BusinessRuleEngine | Pending | — |
| CrossDomainOptimizer | Pending | — |
| LogAnalyst, AutoHealer, PerformanceTuner, IncidentResponder | Pending — `ops/base.py` defines the `OpsAgent` protocol, no concrete agents shipped | — |
| ContainerSandbox | **Deferred** | See B1–B4 above |
| GraphQL compat | Pending | — |
| Container-based sandbox as the default | Superseded in spirit | `ProcessSandbox` + AST static analysis + Phase A observability deliver most of the same risk model without the deploy complexity |
| Full execution-trace recording | **Shipped** | A3 (`SqliteAuditRecorder`) + F8 (`ExecutionTrace.stream_events`) |
| OpenTelemetry integration | **Shipped** | A1 + A2 + A5 |
| `harness validate / simulate` CLI | Partially superseded | A6 `replay` and C6 `eval` cover the "re-run against known inputs" use case; a dedicated `simulate` would be additional, not a replacement |
| RuntimePolicy (dynamic policies) | **Shipped** | `RuntimePolicy` in `harness/policy/runtime_policy.py` |
| Session management | **Shipped** | `SessionManager` in `interface/session.py` |
| ApprovalWorkflow | **Shipped** | `harness/approval/workflow.py` + F5 in-request HITL variant |

---

## How this roadmap stays current

1. **Every increment touches this file.** When `IMPLEMENTATION_LOG.md` gains
   a new "Increment N" entry, `ROADMAP.md` must be updated in the same
   commit — move tasks from **Active** or **Pending** into the **Shipped**
   tables, and refresh the "At a glance" status column.
2. **Metrics come from the codebase, not from memory.** The counts at the
   top of this file are refreshed by running:
   ```bash
   find src/agenticapi -name '*.py' | wc -l        # module count
   find src/agenticapi -name '*.py' -exec cat {} \; | wc -l   # LOC
   uv run pytest --collect-only -q 2>&1 | tail -1  # test count
   ls examples/ | grep -E '^[0-9]' | wc -l          # example count
   ```
3. **Vision stays in `VISION.md`.** Speculative tracks (Phase G/H/I Agent
   Mesh / Flywheel / Capabilities, Phase M/L/T) never appear in this file
   until they're promoted into an active increment.
4. **History stays in `IMPLEMENTATION_LOG.md`.** That file is append-only;
   this file is the current-state rollup.
