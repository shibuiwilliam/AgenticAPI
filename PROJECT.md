# AgenticAPI — Project Document

> **Stable product vision and architectural pillars.**
> For current execution state see [`ROADMAP.md`](ROADMAP.md).
> For speculative forward tracks see [`VISION.md`](VISION.md).
> For the developer guide (commands, conventions, module map) see [`CLAUDE.md`](CLAUDE.md).
> For the append-only shipped-work log see [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md).

---

## Project Overview

**AgenticAPI** is an open-source Python web application framework that
natively integrates coding agents into every layer of web applications.
While conventional web frameworks (FastAPI, Django, Flask) are designed
around the HTTP request/response model, AgenticAPI places *intent-based
interaction* and *dynamically harnessed code generation* at the foundation
of its architecture.

The three core ideas behind AgenticAPI are:

1. **Coding agents as external interfaces.** Instead of REST/GraphQL, an
   agent interface that accepts intents in natural language, dynamically
   generates and executes code (or calls type-hinted tools directly), and
   responds with structured + streaming output.
2. **Agent integration into internal architecture.** Embedding coding
   agents into internal structures such as middleware, validation, data
   access, business logic, and caching to achieve context-aware dynamic
   optimisation.
3. **Autonomous agents for operations and monitoring.** Agents that
   autonomously carry out log analysis, anomaly detection, auto-healing,
   performance optimisation, and incident response.

As a cross-cutting mechanism supporting all of the above, **harness
engineering** is natively integrated into the framework. Harness
engineering is an umbrella term for engineering methodologies that
constrain, monitor, control, and evaluate the behaviour of coding agents.
AgenticAPI provides this as a first-class API: policies, sandboxing,
approval workflows, cost budgets, audit trails, and continuous evaluation
are framework-level concerns, not application concerns.

**In a nutshell:** FastAPI is for type-safe REST APIs. **AgenticAPI is for
harnessed agent APIs.**

---

## Vision and Design Principles

### Vision

> **From "written code that runs" to "agents that understand intent,
> generate optimal code on every request, and produce even better code
> from the results."**

AgenticAPI realises a fundamental paradigm shift in web application
development. It enables the transition from static code to dynamically
generated code across all stages of API design, implementation, and
operations, providing a foundation for systems that self-adapt and
self-evolve.

### Design Principles

**1. Agent-Native.** Coding agents are not add-ons but the foundation of
the framework. Every layer is designed with agent integration as a
premise. Handler signatures can take an `Intent[T]` generic and the LLM
is constrained to produce a conforming payload; tools are plain type-
hinted Python functions decorated with `@tool`; streaming lifecycle
events are declared through a `AgentStream` parameter injected by the
same DI scanner as everything else.

**2. Harness-First.** The balance between agent freedom and safety is
achieved through the harness — a mechanism for constraints, monitoring,
and control. You can declaratively define what agents are allowed to do,
what is forbidden, what requires human approval, how much it can cost,
and how long it can run. The harness runs *every* agent action through
the same pipeline: policy evaluation → AST static analysis →
approval check → sandbox execution → post-execution validators → audit
trail.

**3. Progressive Autonomy.** Agent autonomy levels can be controlled
incrementally. Operations teams can adjust autonomy levels according to
trust, from fully manual to fully autonomous. Autonomy can be evaluated
*live* during a request: an `AutonomyPolicy` with `EscalateWhen` rules
can bubble a running stream up from auto to supervised when conditions
change (latency spike, cost threshold, PII detected), and the stream
fires an `AutonomyChangedEvent` so clients can react.

**4. Observable-by-Default.** All code generated and executed by agents
is automatically subject to traces, logs, and metrics. Full observability
is provided, including the agent's reasoning chain. OpenTelemetry
instrumentation with `gen_ai.*` semantic conventions is shipped as a
framework module, with a zero-op fallback when OTel is not installed.
Prometheus metrics are exposed on `/metrics`. Persistent audit stores
(`SqliteAuditRecorder`) record every intent, policy decision, generated
code block, execution result, and stream event.

**5. Conventional Compatibility.** Compatibility with existing REST APIs
is maintained. AgenticAPI features can be gradually introduced into
existing web applications. Interoperability with FastAPI is a priority:
you can mount a FastAPI sub-app inside an `AgenticApp`, mount an
`AgenticApp` inside a FastAPI app, or expose an agent endpoint as a
conventional REST route via `RESTCompat`. MCP (Model Context Protocol)
compatibility is also shipped.

**6. Pythonic.** Intuitive API design for Python developers. Leverages
type hints, decorators, and async/await, seamlessly integrating with
the Python ecosystem (Pydantic, SQLAlchemy, Celery, etc.). The handler
signature is just a type-hinted `async def` with `Depends()` parameters,
matching FastAPI's ergonomics exactly — the "every line of code you
*don't* write is a line you can't get wrong" philosophy.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                      AgenticAPI Framework                          │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Interface Layer                            │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │   │
│  │  │ Agent        │ │ REST / MCP   │ │ A2A protocol types   │ │   │
│  │  │ Endpoint     │ │ Compat Layer │ │ (scaffolding)        │ │   │
│  │  │ (streaming)  │ │              │ │                      │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                   Harness Engine                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐ │   │
│  │  │ Policies │ │ Process  │ │ Approval │ │ Audit +        │ │   │
│  │  │ (code,   │ │ Sandbox  │ │ Workflow │ │ OTEL +         │ │   │
│  │  │  data,   │ │ + AST    │ │ + F5     │ │ /metrics +     │ │   │
│  │  │  budget, │ │ analysis │ │ in-req   │ │ traceparent    │ │   │
│  │  │  autonomy,│ │          │ │ HITL    │ │                │ │   │
│  │  │  inject) │ │          │ │          │ │                │ │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                  Agent Runtime Layer                          │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │   │
│  │  │ Code         │ │ Context +    │ │ Tool Registry +      │ │   │
│  │  │ Generator +  │ │ Memory       │ │ @tool decorator +    │ │   │
│  │  │ Code Cache   │ │ (C1 stores)  │ │ LLM function calling │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────────┘ │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │   │
│  │  │ LLMBackend   │ │ Prompts      │ │ Evaluation harness   │ │   │
│  │  │ (Anthropic,  │ │ templates    │ │ (EvalSet, judges,    │ │   │
│  │  │  OpenAI,     │ │              │ │  agenticapi eval)    │ │   │
│  │  │  Gemini,     │ │              │ │                      │ │   │
│  │  │  Mock)       │ │              │ │                      │ │   │
│  │  └──────────────┘ └──────────────┘ └──────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                Application Layer                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────────────────┐ │   │
│  │  │ Dynamic  │ │ Dependency│ │ Pipelines, Sessions,        │ │   │
│  │  │ Pipeline │ │ Injection │ │ HTMX, File upload/download  │ │   │
│  │  │          │ │ (Depends) │ │                              │ │   │
│  │  └──────────┘ └──────────┘ └──────────────────────────────┘ │   │
│  │  ┌──────────────────────────────────────────────────────────┐ │   │
│  │  │ AgentMesh — multi-agent orchestration                    │ │   │
│  │  │ @mesh.role / @mesh.orchestrator / MeshContext.call()      │ │   │
│  │  │ cycle detection + budget propagation + trace linkage      │ │   │
│  │  └──────────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                   Ops Agent Layer (scaffolding)               │   │
│  │        OpsAgent base class; concrete agents                   │   │
│  │        (LogAnalyst, AutoHealer, PerfTuner, IncidentResponder) │   │
│  │        are forward-looking — see VISION.md                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Request flow

```
POST /agent/{name} {"intent": "..."}
  -> Authentication (if auth= configured)
  -> IntentParser.parse() -> Intent  or  Intent[T] (D4, structured output)
  -> IntentScope check
  -> Route-level dependencies (D6)
  -> Dependency solver resolves handler params (D1)

  Branch by execution path:
    (a) Handler path            handler(intent, context, ...) -> AgentResponse
    (b) Code-generation path    CodeGenerator -> PolicyEvaluator -> StaticAnalysis
                                 -> ApprovalCheck -> ProcessSandbox -> Monitors -> Validators
    (c) Tool-first path (E4)    single-tool LLM plan -> HarnessEngine.call_tool
                                 -> Policy.evaluate_tool_call -> Tool.invoke
    (d) Streaming path (F1-F8)  handler takes AgentStream param
                                 -> events yielded lazily -> SSE / NDJSON transport
                                 -> AutonomyPolicy live escalation -> request_approval()
                                 -> StreamStore resumability

  Cross-cutting:
    BudgetPolicy estimate + reconcile (A4), approved-code cache (C5),
    OTEL spans (A1), /metrics (A2), SqliteAuditRecorder (A3),
    traceparent propagation (A5), response_model validation (D5).

  -> AgentResponse or streaming event sequence
  -> AgentTasks (background work after response)
```

See [`docs/guides/architecture.md`](docs/guides/architecture.md) for the
user-facing architecture guide. See
[`docs/internals/modules.md`](docs/internals/modules.md) for the
implementation-level module map.

---

## Harness engineering

Harness engineering is the framework's unique load-bearing idea. A
"harness" wraps every agent action with the same pipeline so that *what
is allowed* can be declared once and enforced everywhere. The harness
provides seven layers of defence in depth, each configured declaratively
per endpoint (or application-wide):

1. **Prompt design.** User input is XML-escaped before being embedded in
   LLM prompts to prevent prompt injection. `PromptInjectionPolicy`
   (shipped, ten built-in detection rules) adds a second layer of text
   inspection before the LLM call fires.

2. **Static AST analysis.** Generated code passes through an AST walker
   that enforces forbidden imports, forbidden attribute lookups, forbidden
   `eval`/`exec`/`getattr`, and forbidden file I/O, before it can reach
   the sandbox.

3. **Policy evaluation.** A pluggable set of `Policy` classes — `CodePolicy`,
   `DataPolicy`, `ResourcePolicy`, `RuntimePolicy`, `BudgetPolicy`,
   `AutonomyPolicy`, `PromptInjectionPolicy` — vote on whether to admit
   or reject a given generated code block (or, for E4 tool-first
   execution, a given tool call with specific arguments).

4. **Approval workflow.** Human-in-the-loop intercepts sensitive actions.
   Two flavours: the out-of-band `ApprovalWorkflow` (raise
   `ApprovalRequired`, resolve via a separate endpoint) and the in-request
   `stream.request_approval()` (pause a running stream, auto-register a
   resume endpoint, deliver the decision back to the stream).

5. **Process sandbox.** Code is base64-encoded for transport, executed
   inside an isolated subprocess with timeout enforcement, and its
   output is serialised back through a strict wire format. See
   [`VISION.md`](VISION.md) > Track 2 for container / gVisor / WASM
   hardening plans.

6. **Post-execution monitors + validators.** Runtime resource monitors
   (CPU, memory, wall-clock) and output validators ensure the code's
   side effects and return value are safe before anything is handed
   back to the caller.

7. **Audit trail.** Every request produces a bounded `ExecutionTrace`
   (`SqliteAuditRecorder` for persistence, `InMemoryAuditRecorder` for
   dev). The trace records the intent, the parsed Pydantic payload,
   the generated code, policy outcomes, tool calls, stream events, cost
   breakdown, and final response. The `agenticapi replay <trace_id>`
   CLI re-runs the trace through the live pipeline and diffs the result.

On top of these defensive layers, the framework provides **cost
governance** (`BudgetPolicy` + `PricingRegistry` with HTTP 402 semantic)
and **continuous assurance** (`EvalSet` + five built-in judges + the
`agenticapi eval` CLI).

---

## Technology Stack

| Category | Technology | Rationale |
|---|---|---|
| Language | Python 3.13+ | Modern type syntax (`match`, `type` statements), async/await, strong affinity with the LLM ecosystem |
| Async runtime | `asyncio` (+ optional `uvloop`) | High-performance async I/O |
| HTTP server | `uvicorn` + `starlette` | ASGI-based high-performance server, interop with FastAPI |
| Type system | `pydantic` v2 | Schema definition, validation, JSON Schema emission; underpins `Intent[T]`, `response_model`, `@tool` parameter validation |
| Data models | `pydantic.BaseModel` / `@dataclass(frozen=True, slots=True)` / `StrEnum` / `Protocol` | See coding conventions in [`CLAUDE.md`](CLAUDE.md) |
| LLM clients | `anthropic`, `openai`, `google-genai` SDKs (optional, opt-in extras) | Multi-provider support; each backend maps to an `LLMBackend` protocol |
| Sandbox | `subprocess` (process isolation, Phase 1); planned `gVisor` / `WebAssembly` for production (see `VISION.md`) | Minimal runtime dependency; production-hardening opt-in |
| Static analysis | `ast` (stdlib) + custom analyzers | Forbidden import / eval / getattr detection |
| Storage | `sqlite3` (stdlib) via `asyncio.to_thread` for `SqliteAuditRecorder`, `SqliteMemoryStore`, optional `SqliteFeedbackStore` | Zero new runtime dependencies; drop-in pluggable backends for production |
| Observability | `opentelemetry-api` (optional, no-op fallback) | Standardised spans + metrics + traceparent propagation |
| CLI | `click` / `typer` (stdlib-first) | Pythonic CLI with `dev`, `console`, `replay`, `eval`, `version` |
| Testing | `pytest` + `pytest-asyncio` | Async test support; `MockBackend` for deterministic LLM fixtures |
| Documentation | MkDocs + Material theme + `mkdocstrings` | Auto-generated API reference from Google-style docstrings |

---

## Quality Standards

### Test coverage

- **Unit tests:** 90%+ per module
- **Integration tests:** 100% coverage of major use cases
- **E2E tests:** 100% coverage of example apps (currently 27 examples)
- **Harness tests:** comprehensive coverage of every `PolicyViolation`
  path, sandbox timeout, and approval workflow state
- **Extension tests:** run offline via stub modules; no network access
  required

Actual counts live in [`ROADMAP.md`](ROADMAP.md) > At a glance and are
refreshed every increment.

### Performance targets

| Component | Target |
|---|---|
| `IntentParser.parse()` (keyword path) | < 50 ms |
| `PolicyEvaluator.evaluate()` | < 15 ms |
| Static AST analysis (1,000 lines) | < 50 ms |
| `ProcessSandbox` startup | < 100 ms |
| Streaming first-event latency | < 200 ms |
| Agent endpoint framework overhead vs a plain REST endpoint (excluding LLM call time) | < 500 ms |

### Security standards

- Default protection against OWASP Top 10 at the harness layer
- Built-in LLM prompt injection countermeasures (`PromptInjectionPolicy`,
  shipped)
- Vulnerability detection via static AST analysis of generated code
- Enforced secret-management best practice (env vars and/or a
  `SecretBroker` when `VISION.md` Track 2 lands — secrets must never
  enter an LLM prompt or the audit store)
- Tamper-resistant audit logs (append-only SQLite table; cryptographic
  attestation is a forward-looking goal — see `VISION.md` Track 2)

See [`SECURITY.md`](SECURITY.md) for vulnerability reporting. See
[`docs/guides/security.md`](docs/guides/security.md) for the user-facing
security model.

---

## Community and Governance

### License

MIT License

### Contributing

- Contributor guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Developer guide (commands, conventions, extending): [`CLAUDE.md`](CLAUDE.md)
- Internals (implementation details, testing, CI): [`docs/internals/`](docs/internals/)
- Issue templates: bug reports, feature requests, security reports
  (under `.github/`)
- Automated CI pipeline: lint (ruff), typecheck (mypy `--strict`), test
  (pytest), docs build (mkdocs), pre-commit hooks

### Communication

- GitHub Discussions for design discussions and Q&A
- GitHub Issues for bug reports and feature requests
- Security advisories handled privately — see [`SECURITY.md`](SECURITY.md)

### Governance

- Core maintainers appointed by the project lead
- Design changes proposed through an RFC workflow (markdown files
  discussed via PR)
- Security policy and disclosure procedures in [`SECURITY.md`](SECURITY.md)
- **Durability rule:** every `IMPLEMENTATION_LOG.md` increment entry
  **must** update [`ROADMAP.md`](ROADMAP.md) in the same commit, so the
  shipped / active / deferred / superseded tables never go stale

---

## Competitive Differentiation

| Feature | AgenticAPI | FastAPI | Django | LangServe | CrewAI |
|---|---|---|---|---|---|
| Agent-native | Yes | No | No | Partial | Partial |
| Harness engineering | Yes | No | No | No | No |
| REST compatibility (mount both directions) | Yes | Yes | Yes | No | No |
| Dynamic code generation *with sandbox* | Yes | No | No | No | No |
| Tool-first execution path (skip code-gen when LLM picks a single tool) | Yes | No | No | No | No |
| Policy-based control over generated code | Yes | No | Partial | No | No |
| In-request human-in-the-loop approval | Yes | No | No | No | No |
| Progressive autonomy (escalation during a live stream) | Yes | N/A | N/A | No | Partial |
| Cost governance (request / session / user / endpoint ceilings) | Yes | No | No | No | No |
| Persistent audit trail with replay CLI | Yes | No | No | No | No |
| Continuous evaluation harness (`EvalSet` + judges + CLI) | Yes | No | No | No | No |
| Agent memory protocol (episodic / semantic / procedural) | Partial (C1 shipped; C2 semantic pending) | No | No | Partial | Partial |
| Migration-friendly (drop into existing FastAPI apps) | Yes | N/A | N/A | No | No |
| Forward-looking: governed multi-agent mesh | Planned (`VISION.md` Track 1) | No | No | No | Partial |
| Forward-looking: hardened trust envelope (production-mode, declarative capabilities, attested code) | Planned (`VISION.md` Track 2) | No | No | No | No |
| Forward-looking: self-improving flywheel (outcome feedback → skill mining → prompt auto-tuning) | Planned (`VISION.md` Track 3) | No | No | No | No |

AgenticAPI sits at the unique intersection of *web framework* and *AI
agent framework*. Web frameworks like FastAPI lack agent capabilities;
agent frameworks like LangServe and CrewAI do not account for web
application internal architecture, harness engineering, or production
operability. AgenticAPI unifies both and adds safety, controllability,
observability, and continuous evaluation through harness engineering —
a new category of framework.

---

## Immediate Strategic Priorities

Three elements — identified by independent architect review at Increment 8
— must ship before the longer-term forward tracks become relevant. They
compose: Element 1 makes individual agents production-ready, Element 2 lets
you compose them, Element 3 gets developers to the point where they can try
both in five minutes. Implementation blueprints are in [`CLAUDE.md`](CLAUDE.md)
> Implementation Blueprints.

### Element 1: Native Function Calling for Real LLM Providers

**Severity: CRITICAL — blocks 90%+ of production use cases.**

AgenticAPI defines `ToolCall` types, has a tool-first execution path (E4),
and `MockBackend` fully supports function calling. But the three real
backends (Anthropic, OpenAI, Gemini) do not yet parse provider-native
`tool_use` / `tool_calls` / `function_call` response blocks into `ToolCall`
objects. This means the E4 tool-first path — the framework's most
innovative execution path — only works with `MockBackend`.

**What the fix requires** (per provider): parse tool-use blocks from the
response into `ToolCall` objects, set `finish_reason` correctly, add
`tool_choice` parameter support, add retry with exponential backoff for
transient failures, add integration tests gated behind env vars.

| Framework | Native function calling | Status |
|---|---|---|
| LangChain | All major providers | Production |
| CrewAI | Anthropic + OpenAI | Production |
| **AgenticAPI** | MockBackend only | **Blocked for real providers** |

### Element 2: Multi-Agent Orchestration with Real Execution

**Severity: HIGH — blocks enterprise workflow use cases.**

The `AgentMesh` primitive and `MeshContext.call` are now shipped
(Increment 9+). The remaining work is: HTTP transport for remote mesh
peers, cross-agent budget propagation with parent/child scope linkage,
approval bubbling so sub-agent escalations resolve with one operator
click, and mesh-aware OTEL semconv.

The substrate is ready: `BudgetPolicy` (A4), `ApprovalRegistry` (F5),
`AgentStream` (F1), `traceparent` (A5), `DI scanner` (D1), `Intent[T]`
(D4) are all shipped. The mesh is mechanical glue on top of these.

### Element 3: Developer Onboarding — `agenticapi init` + Starter Templates

**Severity: HIGH — blocks community adoption velocity.**

The `agenticapi init` CLI command is now shipped. The remaining work is:
additional starter templates (`--template chat`, `--template rag`,
`--template tool-calling`) that generate domain-specific projects with
pre-wired streaming, tools, and eval sets.

**Target:** `agenticapi init my-agent && cd my-agent && agenticapi dev
--app app:app` produces a working agent endpoint in under 5 minutes —
with tools, harness, and eval pre-wired.

### Sequencing

```
Element 1: Native function calling   [~2 weeks]  — unblocks production
    ↓
Element 2: Multi-agent mesh (remote) [~2 weeks]  — unblocks enterprise
    ↓
Element 3: More init templates       [~1 week]   — accelerates adoption
```

---

## Strategic Forward Tracks

Three structural capabilities — each building on the existing harness +
audit + streaming substrate — define the framework's longer-term trajectory.
Full task-level specifications live in [`VISION.md`](VISION.md); this
section captures the strategic rationale and competitive framing.

### Why these three (and not something else)

The following were evaluated and explicitly rejected as next priorities:

| Considered | Why rejected |
|---|---|
| Web observability UI | Grafana + OTEL exports already cover this; custom dashboards are a distraction |
| TypeScript / React client SDKs | Valuable but not strategic; buildable externally from the OpenAPI schema |
| Managed / hosted offering | Premature without 10x current user base |
| LangGraph-style graph DSL | Competes on the wrong axis; Python-as-composition is intentionally simpler |
| Additional policy types | 11 types already exist; the next gap is composition, not proliferation |
| Vector database | Use Pinecone / Qdrant / pgvector via a thin protocol later |

The three tracks below were chosen because they each unlock a distinct
stakeholder group that currently has no single framework covering all
three needs, and because they compose onto protocols already shipped
(BudgetPolicy, SqliteAuditRecorder, AgentStream, ApprovalRegistry,
EvalSet, MemoryStore, OTEL, traceparent).

### Track 1: Agent Mesh — governed multi-agent orchestration

**Competitive framing.** LangGraph has graphs but no harness. CrewAI
has agents but no policy. AutoGen has multi-agent chat but no
cost/trace/approval propagation. AgenticAPI is the *only* framework
where multi-agent systems inherit the harness, budgets propagate across
hops, approvals bubble to the nearest human, and audit rows are linked
by `parent_trace_id`.

See [`VISION.md`](VISION.md) > Track 1 for the full task spec
(G1/M3 through G4/M4).

### Track 2: Hardened Trust Model — regulated-industry envelope

**Competitive framing.** No competing framework ships a declarative
capability grant model, kernel-isolated sandbox, secret substitution,
or cryptographic code attestation at the framework level. AgenticAPI is
the *only* framework where `AgenticApp(production=True)` is a
defensible production posture on day one.

See [`VISION.md`](VISION.md) > Track 2 for the full task spec
(I1/T3 through I5/T10).

### Track 3: Self-Improving Flywheel — compound gains over time

**Competitive framing.** No competing framework closes the loop from
audit traces back into prompt tuning, tool promotion, and routing
decisions. AgenticAPI is the *only* framework where every production
request makes the next one cheaper, faster, or more accurate —
in-process, governed, and replayable.

See [`VISION.md`](VISION.md) > Track 3 for the full task spec
(H1/L1 through H6/L7).

### Three-track composition

```
    Shipped substrate         Track 1 (Mesh)        Track 3 (Flywheel)       Track 2 (Trust)
    ╔════════════════╗     ╔════════════════╗     ╔════════════════════╗    ╔════════════════╗
    ║  D/E/F/A/C     ║────>║ AgentMesh      ║     ║ FeedbackStore      ║    ║ Capabilities   ║
    ║  shipped       ║     ║ BudgetScope    ║     ║ ExperienceStore    ║    ║ SecretBroker   ║
    ║                ║     ║ ApprovalBubble ║<────║ SkillMiner         ║<───║ AttestedCode   ║
    ║  (Inc 1-8)     ║     ║ MeshEvent      ║     ║ PromptCompiler     ║    ║ GVisorSandbox  ║
    ╚════════════════╝     ║ HttpTransport  ║     ║ AdaptiveRouter     ║    ║ production=True║
                           ╚════════════════╝     ╚════════════════════╝    ╚════════════════╝
```

**Suggested ordering:** Track 1 (biggest adoption pitch) then Track 2
(regulated-industry unlock) then Track 3 (requires real traffic for
feedstock). A shared `MeshEnvelope` propagation type ships first so the
three tracks cannot diverge. See [`VISION.md`](VISION.md) for the
dependency graph and single-engineer time estimates.

**Target positioning after all three ship:**

> AgenticAPI is the only framework where multi-agent systems inherit the
> harness, every LLM-generated line runs inside a kernel-isolated sandbox
> with declarative capabilities, and the audit trail feeds back into
> prompts, tools, and routing automatically.

---

## Where everything lives

```
AgenticAPI/
├── README.md              ← User landing page (install, 5-min tour)
├── PROJECT.md             ← This file (stable vision + architecture pillars)
├── ROADMAP.md             ← Living execution status (shipped/active/deferred/superseded)
├── VISION.md              ← Speculative forward tracks (Mesh, Trust, Flywheel)
├── CLAUDE.md              ← Developer guide (commands, conventions, module map)
├── IMPLEMENTATION_LOG.md  ← Append-only log of shipped increments
├── CONTRIBUTING.md        ← Contributor onboarding
├── SECURITY.md            ← Vulnerability reporting
│
├── src/agenticapi/        ← Framework source
├── tests/                 ← unit / integration / e2e / benchmarks
├── examples/              ← 27 runnable example apps (01 → 27)
├── extensions/            ← Separately-installable extensions
│     └── agenticapi-claude-agent-sdk/
│
├── docs/                  ← mkdocs site (served at /docs URL)
│   ├── index.md           ← Docs hub
│   ├── getting-started/   ← Installation, quick start, examples tour
│   ├── guides/            ← User-facing how-to guides
│   ├── api/               ← Auto-generated API reference pages
│   └── internals/         ← Contributor-facing implementation notes
│
├── development/           ← Internal engineering docs for contributors + Claude Code
│
├── mkdocs.yml             ← docs site config
├── pyproject.toml         ← package config
├── Makefile               ← convenience targets
└── uv.lock                ← pinned dependency lock
```

For the precise file-by-file module map, see
[`docs/internals/modules.md`](docs/internals/modules.md).
