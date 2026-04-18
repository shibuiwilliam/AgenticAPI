# development/ — Internal Engineering Documents

Technical references for contributors and Claude Code sessions. **Not** user-facing documentation (that lives under `docs/` and is published via mkdocs).

## Document Index

| Document | Purpose |
|---|---|
| [architecture.md](architecture.md) | Implementation architecture: 6-layer module dependency graph, request lifecycle through all 4 execution paths, DI scanner internals, harness pipeline, streaming transports, mesh orchestration, memory subsystem |
| [modules.md](modules.md) | Complete module reference: every file in `src/agenticapi/` organized by subpackage with purpose, line count, and key exports |
| [testing.md](testing.md) | Testing strategy: directory layout, MockBackend patterns, e2e test conventions, per-module coverage targets, benchmark suite |
| [extending.md](extending.md) | Step-by-step recipes for adding policies, tools, LLM backends, examples, CLI commands, and extension packages |
| [security.md](security.md) | Security model: seven defense layers, prompt-injection detection, PII policy, pre-LLM input scanning, sandbox isolation, audit trail |

## Current Codebase Stats

| Metric | Value |
|---|---|
| Python modules in `src/agenticapi/` | 141 (128 core + 13 in-tree extension) |
| Lines of code | ~26,725 |
| Tests collected (excl. benchmarks) | 1,507 |
| Example apps | 32 |
| Public API symbols (`__all__`) | 86 |
| Policy classes | 11 (Code, Data, Resource, Runtime, Budget, Autonomy, PromptInjection, PII + base, evaluator, pricing) |
| LLM backends | 4 (Anthropic, OpenAI, Gemini, Mock) — all with native function calling, multi-turn tool conversations, + retry |
| CLI subcommands | 7 (dev, console, replay, eval, init, version, bump) |
| Extension packages | 1 (`agenticapi-claude-agent-sdk`) |
| Core subsystems | Agentic Loop (ReAct), Workflow Engine, Playground UI, Trace Inspector, Harness MCP Server |

## Relationship to Other Documents

- **CLAUDE.md** — Concise developer guide: setup, CLI commands, coding conventions, Key Types table, implementation blueprints for upcoming tasks. Start there.
- **PROJECT.md** — Product vision, design principles, architecture overview, strategic priorities.
- **ROADMAP.md** — Single source of execution truth: shipped / active / deferred tables.
- **docs/** — User-facing documentation served by mkdocs. Written for framework consumers.
- **docs/internals/** — Contributor-facing docs that are also published via mkdocs (a lighter, more user-accessible version of these internal docs).

## Conventions

- File paths are relative to the repository root.
- Line references are approximate — search for the referenced symbol name if stale.
- When a document says "Phase X" or "Increment N", it refers to the roadmap identifiers in `ROADMAP.md` / `IMPLEMENTATION_LOG.md`.
