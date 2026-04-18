# AgenticAPI

**Agent-native web framework with harness engineering for Python.**

AgenticAPI lets you build web applications where endpoints accept natural language intents, dynamically generate code via LLMs, and execute it in a sandboxed, policy-controlled environment. Think of it as **FastAPI for agent-powered APIs** — with safety guardrails built in.

```python
from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="Hello Agent")

@app.agent_endpoint(name="greeter", autonomy_level="auto")
async def greeter(intent: Intent, context: AgentContext) -> AgentResponse:
    return AgentResponse(
        result={"message": f"Hello! You said: {intent.raw}"},
        reasoning="Direct greeting response",
    )
```

```bash
agenticapi dev --app myapp:app
# Swagger UI at http://127.0.0.1:8000/docs
```

## Highlights

- **Intent-based endpoints** — Natural language in, structured results out
- **Typed intents** — Schema-aware `Intent[T]` parsing with validation and OpenAPI publication
- **Dynamic code generation** — LLMs generate Python code on the fly
- **Native function calling** — `ToolCall` + `tool_choice` + `finish_reason` across all four backends (Anthropic, OpenAI, Gemini, Mock) with automatic retry
- **Harness engineering** — Policies, static analysis, sandbox, audit trails
- **Persistent audit** — In-memory for dev or `SqliteAuditRecorder` for production
- **Cost budgeting** — `BudgetPolicy` and `PricingRegistry` primitives for LLM spend ceilings
- **Observability** — OpenTelemetry spans, Prometheus metrics, W3C trace propagation — all graceful no-ops when unused
- **Dependency injection** — FastAPI-style `Depends()` with generator-based teardown
- **Tool decorator** — `@tool` turns plain functions into registered tools with auto-generated JSON schemas
- **Multi-LLM** — Anthropic Claude, OpenAI GPT, Google Gemini, or your own
- **Authentication** — API key, Bearer token, Basic auth — per-endpoint or app-wide
- **Custom responses** — `HTMLResult`, `PlainTextResult`, `FileResult`, or any Starlette `Response`
- **HTMX support** — `HtmxHeaders` auto-injection, partial page updates
- **File handling** — Upload via multipart, download via `FileResult`, streaming
- **MCP support** — Expose endpoints as MCP tools for Claude Desktop, Cursor, etc.
- **OpenAPI / Swagger / ReDoc** — Auto-generated, like FastAPI
- **Background tasks** — Post-response processing via `AgentTasks`
- **Approval workflows** — Human-in-the-loop for sensitive operations
- **ASGI-native** — Built on Starlette, runs on uvicorn

- **Multi-agent orchestration** — `AgentMesh` with `@mesh.role` / `@mesh.orchestrator`, budget propagation, cycle detection
- **Agentic loop** — Multi-turn ReAct pattern where the LLM autonomously calls tools and reasons to a final answer, all harness-governed
- **Workflow engine** — Declarative multi-step workflows with typed state, conditional branching, parallel execution, checkpoints
- **Agent playground** — Self-hosted debugger UI at `/_playground` for chatting with agents and inspecting execution traces
- **Trace inspector** — Self-hosted trace inspection UI at `/_trace` with search, diff, cost analytics, and compliance export
- **Harness-governed MCP** — `HarnessMCPServer` exposes `@tool` functions as MCP tools with full policy enforcement, audit, and budget tracking
- **Multi-turn tool conversations** — `LLMMessage` carries `tool_call_id` and `tool_calls` for provider-native multi-turn format translation across Anthropic, OpenAI, and Gemini
- **Project scaffolding** — `agenticapi init` generates a ready-to-run project with tools, harness, and eval set

**Current scale:** 141 Python modules, ~26,725 lines of code, **1,507 tests** (+38 in extensions), 32 examples, 1 extension.

For the full shipped / active / deferred / superseded status matrix see `ROADMAP.md` at the repo root. For speculative forward tracks (Agent Mesh, Hardened Trust, Self-Improving Flywheel) see `VISION.md` at the repo root.

## Quick Links

**Getting started**

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quickstart.md)
- [Examples](getting-started/examples.md) — 32 runnable apps from hello-world to agentic workflows

**Core guides**

- [Architecture](guides/architecture.md)
- [Intent System](guides/intents.md) / [Typed Intents](guides/typed-intents.md)
- [Dependency Injection](guides/dependency-injection.md)
- [Harness & Safety](guides/harness.md) / [Security Model](guides/security.md)
- [Cost Budgeting](guides/cost-budgeting.md)
- [Observability](guides/observability.md)
- [Authentication](guides/authentication.md)
- [File Handling](guides/file-handling.md) / [HTMX Support](guides/htmx.md)
- [LLM Backends](guides/llm-backends.md) / [Tools](guides/tools.md) / [Tool Decorator](guides/tool-decorator.md)
- [Streaming](guides/streaming.md) / [Agent Memory](guides/memory.md)
- [Eval Harness](guides/eval-harness.md) / [Safety Policies](guides/safety-policies.md)
- [Approval Workflows](guides/approval.md) / [Sessions](guides/sessions.md)
- [Agent Mesh](guides/mesh.md) / [REST Compatibility](guides/rest-compat.md) / [Agent-to-Agent](guides/a2a.md)
- [Ops Agents](guides/ops-agents.md)
- [OpenAPI & Swagger](guides/openapi.md)
- [Testing](guides/testing.md)

**For contributors**

- [Internals → Current State](internals/current-state.md)
- [Internals → Module Reference](internals/modules.md)
- [Internals → Extending the Framework](internals/extending.md)
- [Internals → Extensions Architecture](internals/extensions.md)
- [Internals → Contributing](internals/contributing.md)

**Reference**

- [API Reference](api/app.md) — every public class and function
- [GitHub Repository](https://github.com/shibuiwilliam/AgenticAPI)
