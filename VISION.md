# AgenticAPI — Vision

> **These are speculative tracks, not committed work.**
> For current execution state see [`ROADMAP.md`](ROADMAP.md).
> For the append-only shipped-work log see [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md).
> For stable product vision see [`PROJECT.md`](PROJECT.md).

This file collects the forward-looking tracks that sit beyond the current
roadmap. Each track pairs a **developer-facing "DX" plane** (the decorator
API, the Pydantic types, the error messages) with a **runtime plane** (the
storage, the enforcement machinery, the background loops). The DX plane
originated in `PROJECT.md` > Immediate Strategic Priorities; the runtime plane
originated in `CLAUDE.md` > Implementation Blueprints. Both are preserved here
in condensed form so that any track can be promoted into `ROADMAP.md`
without hunting through archived docs.

None of the tracks below are on a fixed schedule. They are listed in
rough priority order — multi-agent mesh first (biggest adoption pitch),
then hardened trust (regulated-industry unlock), then the self-improving
flywheel (the "gets better every request" pitch).

---

## Track 1: Agent Mesh — governed multi-agent orchestration

**DX plane:** Phase G (from PROJECT.md).
**Runtime plane:** Phase M (from CLAUDE.md).

**Vision.** Write multi-agent systems the way FastAPI users write routers.
Declare roles. Declare an orchestrator. Every cross-agent call is a
`mesh_ctx.call("role", payload)` that is type-checked at compile time,
policy-checked at call time, budget-debited on return, audit-recorded end
to end, trace-propagated as a child span, and approval-bubbled to the
nearest human if any sub-agent escalates.

**Why it's a differentiator.** LangGraph has graphs but no harness.
CrewAI has agents but no policy. AutoGen has multi-agent chat but no
cost/trace/approval propagation. Combining a mesh primitive with the
already-shipped harness substrate is a unique position.

### What gets built

| ID | Task | Plane | Deliverable |
|---|---|---|---|
| G1 / M3 | `AgentMesh` primitive + `@mesh.role` / `@mesh.orchestrator` decorators + `MeshContext.call` | DX + runtime | `src/agenticapi/mesh/*`; `LocalTransport` + `HttpTransport` |
| G2 / M1 | Cross-agent budget scope propagation (`BudgetScope` with parent/child linkage) | runtime | Parent budget limit shared by all sub-agents |
| G2 / M2 | Approval bubbling — sub-agent `request_approval` resolves against the parent's ticket | runtime | One operator click accepts the whole mesh |
| G3 / M5 | Mesh-aware OpenAPI + audit + OTEL semconv (`gen_ai.agent.role`, `agenticapi.mesh.depth`) | DX + runtime | `/mesh.json`; audit rows linked by `parent_trace_id` |
| G4 / M4 | `MeshEvent` envelope on `AgentStream` for sub-agent events | DX + runtime | SSE shows `mesh_role_started` / `mesh_role_completed` |

### Substrate it already depends on (all shipped)

- D1 (DI scanner for `MeshContext` injection)
- D4 (`Intent[T]` for typed role payloads)
- A3 (SqliteAuditRecorder for linked audit rows)
- A4 (BudgetPolicy for scope propagation)
- A5 (traceparent for distributed mesh traces)
- F1 (AgentStream for nested events)
- F5 (ApprovalRegistry for bubbling)

### Success criteria

- A 3-role mesh declared in ≤30 lines, exposed at `POST /agent/<orchestrator>`,
  returns typed results, and all sub-spans appear as children of the
  orchestrator span in OTEL.
- `BudgetPolicy(max_per_request_usd=0.50)` shared by all sub-agents —
  the second sub-agent that would breach the wallet fails with
  `BudgetExceeded`.
- Sub-agent `request_approval` calls resolve on a single operator click.
- `examples/21_research_mesh/` (in-process) and `examples/22_distributed_mesh/`
  (HTTP transport between two instances) exist and pass e2e tests.

---

## Track 2: Hardened Trust Model — regulated-industry envelope

**DX plane:** Phase I (from PROJECT.md).
**Runtime plane:** Phase T (from CLAUDE.md).

**Vision.** Every generated code block runs with the exact privileges it
needs and nothing more, declared on the endpoint and enforced by the
sandbox. Secrets never appear in prompts. Network egress is allow-listed.
Filesystem access is read/write partitioned. Every execution is
cryptographically attested. AgenticAPI is the only agent framework where
this is declarative, framework-level, and on by default in production mode.

**Why it's a differentiator.** This track un-defers `ROADMAP.md` Phase B
(`B1–B4`, `B6–B8`) and rebrands it as a coherent trust envelope. Without
this, the "harness-first" positioning cannot be defended under adversarial
scrutiny, and regulated-industry prospects have no path to adoption.

### What gets built

| ID | Task | Plane | Deliverable |
|---|---|---|---|
| I1 / T3 | `Capabilities` Pydantic type + `compile_for_backend` translator | DX + runtime | One declarative surface for filesystem / network / env / secrets |
| I2 / T4 | `SecretBroker` + sandbox-side substitution (secrets never touch LLM prompt, audit row, or logs) | DX + runtime | `EnvSecretBroker`, `VaultSecretBroker`, adversarial grep test |
| I3 / T5 | `AttestedCode` — Ed25519 signing of every generated code block + `agenticapi verify <trace_id>` CLI | DX + runtime | Tamper test: rewriting an audit row fails `verify` |
| I4 | `@tool(capabilities=...)` — tool capabilities intersect with endpoint capabilities at registration time | DX | Rejection at registration time if not a subset |
| I5 / T10 | `AgenticApp(production=True)` fail-closed mode: gVisor sandbox, deny-by-default capabilities, mandatory attestation | DX + runtime | One-line flip from dev to prod posture |
| T1 | `GVisorSandbox` — kernel-level isolation via `runsc` runtime | runtime | Same sandbox contract tests as `ProcessSandbox`, passing under gVisor |
| T2 | `WasmSandbox` — Pyodide / `wasmtime-py`, opt-in `agenticapi[wasm]` extra | runtime | Second-line option for macOS dev and edge |
| T6 | `PromptInjectionPolicy` — **already shipped** as B5 in Increment 7 | runtime | Expanded detection corpus + tuning |
| T7 | `PIIPolicy` — email / phone / SSN / credit card / IBAN / IP detection + redaction | runtime | Adversarial test for PII round-tripping |
| T8 | Delegation JWTs for `HttpTransport` cross-mesh calls | runtime | Scoped tokens = parent caps ∩ sub-agent declared caps |
| T9 | Adversarial test suite as CI quality gate | runtime | `tests/adversarial/` runs on every PR; exit 1 on any failure |

### Substrate it already depends on

- B5 PromptInjectionPolicy (shipped Increment 7 — the first Phase B task to land)
- E4 `evaluate_tool_call` hook (shipped Increment 6 — used for per-tool capability enforcement)
- A1 OTEL (sandbox events recorded as span events)
- A3 SqliteAuditRecorder (attestation persistence)

### Success criteria

- `AgenticApp(production=True)` refuses to start until every endpoint has
  a `capabilities=` declaration; once declared, the app runs under
  `GVisorSandbox` with prompt-injection, PII, and attested-code policies
  automatically active.
- `pytest tests/adversarial/` passes on `GVisorSandbox` in CI with gVisor
  installed.
- An adversarial grep test scans every audit row, log line, span attribute,
  and response body for a real secret string and returns zero matches,
  while the sandboxed code successfully uses the secret to make an HTTPS
  call.
- `docs/production-checklist.md` exists and reads as a confident claim
  that AgenticAPI is safe to deploy for regulated workloads.

---

## Track 3: Self-Improving Flywheel

**DX plane:** Phase H (from PROJECT.md).
**Runtime plane:** Phase L (from CLAUDE.md).

**Vision.** Every production request is also a training signal. The
agent's prompts, tools, cached code, and router weights improve
automatically from (a) outcome feedback from users, (b) judge scores
from the eval harness, and (c) audit-trace statistics — all in-process,
all governed by the harness, all shipped as one CLI command.

**Why it delivers the original `PROJECT.md` vision.** `PROJECT.md` promises
"agents that understand intent, generate optimal code on every request,
and produce even better code from the results." The framework currently
fulfils the first two clauses but not the third: audit traces are recorded,
never fed back into the generation path. This track closes that loop.

### What gets built

| ID | Task | Plane | Deliverable |
|---|---|---|---|
| H1 / L1–L2 | `FeedbackStore` + `SqliteFeedbackStore` + auto-mounted `POST /feedback/{trace_id}` | DX + runtime | Client-facing outcome-rating surface, auth-gated, PII-redacted |
| H2 / L3 | `ExperienceStore` — audit ⋈ feedback joined view with `query_top_successful`, `query_regressions`, `query_by_intent` | DX + runtime | One queryable shape the flywheel reads from |
| H3 / L4 | `SkillMiner` — promote successful codegen (by AST-normalised hash) into `@tool`-decorated registry entries | DX + runtime | Seeded test: 10 successful traces → 1 candidate with confidence ≥0.8 |
| H4 / L5 | `PromptCompiler` — DSPy-style prompt auto-tuning bounded by `BudgetPolicy`; `agenticapi train` CLI | DX + runtime | Synthetic eval set shows measurable improvement after training |
| H5 / L6 | `AdaptiveRouter` — `DynamicPipeline` stage that picks historically-cheapest endpoint+model for a given intent class | DX + runtime | Two equivalent endpoints; cheaper one is auto-selected |
| H6 / L7 | `GET /train.json` — flywheel introspection endpoint (top skills, current prompt versions, router decisions, feedback trends) | DX + runtime | Documented JSON shape + Grafana panel |

### Substrate it already depends on

- A3 SqliteAuditRecorder (the feedstock)
- A6 replay primitive (for evaluating prompt variants)
- C1 MemoryStore (for long-lived experience records)
- C5 approved-code cache (subsumed by `SkillMiner` promotions)
- C6 EvalSet (for `PromptCompiler` objective scoring)
- E4 tool-first execution path (promoted skills become tools)
- D5 response_model (for outcome classification)

### Success criteria

- An `OutcomeFeedback` POST against a trace returns 202 and the row is
  visible in the feedback sqlite store.
- `SkillMiner.mine(window_days=7)` returns real candidates on a synthetic
  seeded corpus with confidence ≥0.8.
- `agenticapi train --endpoint orders --eval-set eval/orders.yaml
  --budget-usd 2.00 --iterations 10` produces a measurable improvement
  visible in `/train.json` on the next request.
- `AdaptiveRouter` auto-selects the historically-cheaper endpoint for
  identical new intents.
- `examples/23_flywheel/` exists and demonstrates end-to-end.

---

## Track dependency graph

```
        Shipped substrate        Track 1 (Mesh)       Track 3 (Flywheel)      Track 2 (Trust)
        ╔════════════════╗    ╔════════════════╗    ╔════════════════════╗   ╔════════════════╗
        ║  D/E/F/A/C     ║───▶║ G1/M3 primitive║    ║ H1/L1 feedback     ║   ║ I1/T3 caps     ║
        ║  shipped       ║    ║ G2/M1 budget   ║    ║ H2/L3 experience   ║   ║ I2/T4 secrets  ║
        ║                ║    ║ G2/M2 approval ║◀───║ H3/L4 skill miner  ║◀──║ I3/T5 attested ║
        ║  (Inc 1–7)     ║    ║ G3/M5 openapi  ║    ║ H4/L5 prompt cmplr ║   ║ I4 tool inter. ║
        ╚════════════════╝    ║ G4/M4 stream   ║    ║ H5/L6 router       ║   ║ I5/T10 prod    ║
                               ╚════════════════╝    ║ H6/L7 /train.json  ║   ║ T1 GVisor      ║
                                                     ╚════════════════════╝   ║ T2 Wasm        ║
                                                                               ║ T7 PII         ║
                                                                               ║ T8 delegation  ║
                                                                               ║ T9 adversarial ║
                                                                               ╚════════════════╝
```

Suggested single-engineer ordering (once current `ROADMAP.md` priorities
are discharged):

1. **Track 1 (Mesh)** — 4–6 days. First differentiator live.
2. **Track 2 (Trust)** — 5–7 days. Second differentiator live; un-defers
   Phase B.
3. **Track 3 (Flywheel)** — 6–8 days, after C6 is polished. Third
   differentiator live.

---

## Historical Appendix — Original `PROJECT.md` Phase 2 roadmap

The original `PROJECT.md` (2026-04-07 baseline) ended with a "Phase 2
Roadmap" table listing modules and subsystems targeted for v0.2. Several
of those items were delivered but via different mechanisms than originally
planned; several remain pending; several have been superseded. This
appendix preserves the original list for readers coming from early blog
posts or external references.

| Original Phase 2 item | Original location | Status today | Notes |
|---|---|---|---|
| A2A Server/Client | `interface/a2a/server.py`, `client.py` | **Partial** | `interface/a2a/{protocol,capability,trust}.py` types exist (~80 LOC). Server / client / discovery pending. Likely to be absorbed by Track 1 (Mesh). |
| Service Discovery | `interface/a2a/discovery.py` | Pending | Likely to be absorbed by Track 1 when `HttpTransport` lands. |
| AdaptiveDataAccess | `application/data_access.py` | Pending | No concrete customer demand yet. |
| BusinessRuleEngine | `application/business_rules.py` | Pending | Unblocked by D4 `Intent[T]`; no demand yet. |
| CrossDomainOptimizer | `application/cross_domain.py` | Pending | Superseded in spirit by Phase F streaming + F6 `AutonomyPolicy`. |
| LogAnalyst | `ops/log_analyst.py` | Pending | `ops/base.py` defines `OpsAgent` protocol; no concrete agents shipped. |
| AutoHealer | `ops/auto_healer.py` | Pending | Same. |
| PerformanceTuner | `ops/perf_tuner.py` | Pending | Same. |
| IncidentResponder | `ops/incident.py` | Pending | Same. |
| ContainerSandbox | `harness/sandbox/container.py` | **Deferred** | Replaced by Track 2 Phase T1 `GVisorSandbox`. See `ROADMAP.md` > Deferred. |
| GraphQL compat | `interface/compat/graphql.py` | Pending | Low priority; REST compat shipped. |
| Container-based sandbox as default | architectural | **Superseded** | `ProcessSandbox` + AST static analysis + Phase A observability deliver most of the same risk model at lower deploy complexity. Track 2 un-defers container isolation as opt-in production-mode. |
| Full execution-trace recording | `harness/audit/` | **Shipped** | A3 `SqliteAuditRecorder` + F8 `ExecutionTrace.stream_events`. |
| OpenTelemetry integration | `observability/` | **Shipped** | A1 + A2 + A5. |
| `harness validate / simulate` CLI | `cli/harness.py` | Partial | A6 `replay` + C6 `eval` cover the "re-run against known inputs" use case. A dedicated `simulate` would be additional, not a replacement. |
| RuntimePolicy (dynamic policies) | `harness/policy/runtime_policy.py` | **Shipped** | Inc 1. |
| Session management | `interface/session.py` | **Shipped** | `SessionManager`. |
| ApprovalWorkflow | `harness/approval/workflow.py` | **Shipped** | `harness/approval/workflow.py` + F5 in-request HITL variant. |

**How to read this table.** Items marked **Shipped** or **Partial** are
the cases where v0.2 delivery matched or improved on the original plan.
Items marked **Pending** are still valid future work but have no customer
demand or clear differentiator case; they are eligible to be promoted into
`ROADMAP.md` > Active when one of those conditions changes. Items marked
**Deferred** or **Superseded** have been explicitly replaced by a newer
design — the "Notes" column points at what replaced them.

---

## How this vision stays honest

1. **Nothing in this file has a ship date.** The only document with ship
   dates is `ROADMAP.md`.
2. **Promotion is explicit.** Moving a track from `VISION.md` into an
   active increment means updating `ROADMAP.md` to list the tasks,
   writing a design spec in the same commit, and cross-referencing
   `VISION.md` → `ROADMAP.md` for that track.
3. **Deferral is explicit.** If a track is no longer viable (customer
   research disproves the pitch, a substrate dependency breaks,
   alternative tool becomes canonical), delete it from this file — don't
   let it rot.
4. **History lives in the archive.** The full task-level specs for
   Phases G/H/I/M/L/T remain in `PROJECT.md > Immediate Strategic Priorities and
   CLAUDE.md > Implementation Blueprints.
   original rationale.
