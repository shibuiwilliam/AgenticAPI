# AgenticAPI

**The agent-native web framework for Python.** Build APIs where endpoints understand natural language, call tools autonomously, and execute safely behind a multi-layered harness — with the developer ergonomics you know from FastAPI.

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-yellow.svg)](./LICENSE)
[![Tests](https://img.shields.io/badge/tests-1520%20passing-brightgreen.svg)]()
[![Examples](https://img.shields.io/badge/examples-32%20runnable-blueviolet.svg)](./examples)

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
curl -X POST http://127.0.0.1:8000/agent/greeter \
    -H "Content-Type: application/json" \
    -d '{"intent": "Hello, how are you?"}'
```

You instantly get Swagger UI at `/docs`, ReDoc at `/redoc`, an OpenAPI 3.1 spec at `/openapi.json`, and `/health` + `/capabilities` endpoints — no extra wiring.

---

## Table of Contents

- [Why AgenticAPI?](#why-agenticapi)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Quick Tour](#quick-tour)
- [How It Maps to FastAPI](#how-it-maps-to-fastapi)
- [Features at a Glance](#features-at-a-glance)
- [The Harness: Safety by Default](#the-harness-safety-by-default)
- [Agentic Loop](#agentic-loop)
- [Workflow Engine](#workflow-engine)
- [Agent Playground & Trace Inspector](#agent-playground--trace-inspector)
- [Multi-Agent Orchestration](#multi-agent-orchestration)
- [Native Function Calling](#native-function-calling)
- [Harness-Governed MCP Tool Server](#harness-governed-mcp-tool-server)
- [LLM Backends](#llm-backends)
- [Tools](#tools)
- [Authentication](#authentication)
- [Streaming](#streaming)
- [Cost Budgeting](#cost-budgeting)
- [Agent Memory](#agent-memory)
- [Custom Responses, HTMX & File Handling](#custom-responses-htmx--file-handling)
- [MCP & REST Compatibility](#mcp--rest-compatibility)
- [Observability](#observability)
- [Extensions](#extensions)
- [Examples](#examples)
- [CLI Reference](#cli-reference)
- [Development](#development)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Why AgenticAPI?

> **FastAPI is for type-safe REST APIs. AgenticAPI is for harnessed agent APIs.**

Traditional web frameworks expect structured request bodies. AgenticAPI endpoints accept natural-language **intents** instead. Under the hood an LLM can parse those intents into Pydantic schemas, choose tools via native function calling, or generate Python code — and a multi-layered **harness** evaluates, sandboxes, budgets, and audits every execution before it ever touches your data.

The best part: **you can use it with or without an LLM.**

- **Without an LLM** — a clean decorator-based ASGI framework with FastAPI-like ergonomics: dependency injection, `response_model` validation, authentication, OpenAPI docs, HTMX support, file upload/download, streaming (SSE + NDJSON), background tasks, and more.
- **With an LLM** — a complete agent execution platform: multi-turn agentic loops, declarative workflows, native function calling across Anthropic/OpenAI/Gemini, policy enforcement, process sandboxing, approval workflows, persistent audit trails, agent memory, code caching, autonomy escalation, multi-agent orchestration, and full observability.

Either way you get **32 runnable examples** to copy from, **1,520 passing tests** that prove every feature works, and a production-ready observability story (OpenTelemetry spans, Prometheus metrics, W3C trace propagation — all optional, all graceful no-ops when unused).

---

## Installation

**Python 3.13+** is required.

```bash
pip install agentharnessapi
```

For development:

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
uv sync --group dev    # or: pip install -e ".[dev]"
```

Optional extras:

```bash
pip install agentharnessapi[mcp]                  # MCP server support
pip install agentharnessapi[claude-agent-sdk]      # Full Claude Agent SDK loop

# Observability — all optional, all graceful no-ops when missing
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
pip install prometheus-client
```

---

## Quick Start

The fastest way to create a new project:

```bash
agenticapi init my-agent
cd my-agent
agenticapi dev --app app:app
```

This generates a ready-to-run project with a handler, tools, harness, and an eval set — all wired together. It works immediately with `MockBackend` (no API key needed). Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY` to switch to a real provider.

```
my-agent/
  app.py              # AgenticApp with one endpoint + harness + tools
  tools.py            # Two @tool-decorated functions
  evals/golden.yaml   # Three eval cases for regression testing
  .env.example        # API key placeholders
  pyproject.toml      # Dependencies
  README.md           # Run instructions + curl walkthrough
```

Test it:

```bash
curl -X POST http://localhost:8000/agent/ask \
  -H "Content-Type: application/json" \
  -d '{"intent": "hello world"}'
```

Run evals:

```bash
agenticapi eval --set evals/golden.yaml --app app:app
```

---

## Quick Tour

### 1. Minimal endpoint (no LLM needed)

```python
from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="My Service")

@app.agent_endpoint(name="orders", autonomy_level="auto")
async def order_agent(intent: Intent, context: AgentContext) -> AgentResponse:
    return AgentResponse(result={"order_count": 42})
```

```bash
agenticapi dev --app myapp:app
curl -X POST http://127.0.0.1:8000/agent/orders \
    -H "Content-Type: application/json" \
    -d '{"intent": "How many orders do we have?"}'
```

Every app automatically registers `/health`, `/capabilities`, `/docs`, `/redoc`, and `/openapi.json`.

### 2. With an LLM and the safety harness

```python
from agenticapi import AgenticApp, CodePolicy, DataPolicy, HarnessEngine
from agenticapi.runtime.llm.anthropic import AnthropicBackend

app = AgenticApp(
    title="Harnessed Agent",
    llm=AnthropicBackend(),  # reads ANTHROPIC_API_KEY from env
    harness=HarnessEngine(
        policies=[
            CodePolicy(denied_modules=["os", "subprocess"], deny_eval_exec=True),
            DataPolicy(readable_tables=["orders", "products"], deny_ddl=True),
        ],
    ),
)

@app.agent_endpoint(name="analytics", autonomy_level="supervised")
async def analytics(intent, context):
    pass  # The harness pipeline takes over from here
```

The pipeline: **parse intent -> generate code via LLM -> evaluate policies -> AST analysis -> approval check -> process sandbox -> monitors/validators -> audit trace -> response**.

### 3. Typed intents

Constrain the LLM's output to a Pydantic schema — full validation before the handler runs:

```python
from pydantic import BaseModel, Field
from agenticapi import Intent

class OrderSearch(BaseModel):
    status: str | None = None
    limit: int = Field(default=10, ge=1, le=100)

@app.agent_endpoint(name="orders.search")
async def search(intent: Intent[OrderSearch], context):
    query = intent.params  # already validated, fully typed
    return {"status": query.status, "limit": query.limit}
```

### 4. Dependency injection

FastAPI-style `Depends()` with generator-based teardown:

```python
from agenticapi import Depends

async def get_db():
    async with engine.connect() as conn:
        yield conn  # teardown after handler runs

@app.agent_endpoint(name="orders")
async def list_orders(intent, context, db=Depends(get_db)):
    return {"orders": await db.fetch("SELECT * FROM orders")}
```

### 5. Programmatic usage (no HTTP)

```python
response = await app.process_intent(
    "Show me last month's orders",
    endpoint_name="orders.query",
    session_id="session-123",
)
print(response.result)
```

---

## How It Maps to FastAPI

| FastAPI | AgenticAPI | Notes |
|---|---|---|
| `FastAPI()` | `AgenticApp()` | Main app, ASGI-compatible |
| `@app.get("/path")` | `@app.agent_endpoint(name=...)` | Endpoint registration |
| `APIRouter` | `AgentRouter` | Grouping with prefix and tags |
| `Request` | `Intent` / `Intent[T]` | Input (natural language instead of typed params) |
| `Response` | `AgentResponse` | Output with result, reasoning, trace |
| `BackgroundTasks` | `AgentTasks` | Post-response task execution |
| `Depends()` | `Depends()` | Dependency injection (same name, same shape) |
| `response_model=` | `response_model=` | Pydantic validation + OpenAPI schema |
| `app.add_middleware()` | `app.add_middleware()` | Starlette middleware (CORS, etc.) |
| `UploadFile` | `UploadedFiles` | File upload via multipart |
| `FileResponse` | `FileResult` | File download |
| `HTMLResponse` | `HTMLResult` | HTML response |
| Security schemes | `Authenticator` | API key, Bearer, Basic auth |
| `/docs` | `/docs` | Swagger UI (auto-generated) |

---

## Features at a Glance

| Category | What you get |
|---|---|
| **Agent endpoints** | Decorator-based registration, natural-language intents, routers with prefix/tags |
| **Agentic loop** | Multi-turn ReAct pattern — LLM autonomously calls tools and reasons to a final answer, all harness-governed |
| **Workflow engine** | Declarative multi-step workflows with typed state, conditional branching, parallel execution, checkpoints |
| **Agent playground** | Self-hosted debugger UI at `/_playground` for chatting with agents and inspecting execution traces |
| **Trace inspector** | Self-hosted trace inspection UI at `/_trace` with search, diff, cost analytics, and compliance export |
| **Typed intents** | Constrain LLM output to a Pydantic schema with `Intent[T]` — full validation, IDE autocompletion |
| **Multi-LLM** | Anthropic Claude, OpenAI GPT, Google Gemini, deterministic Mock — swap with one line |
| **Native function calling** | Provider-native `ToolCall` + `finish_reason` + `tool_choice` across every backend, with retry and backoff |
| **Harness MCP server** | Expose `@tool` functions as MCP tools with full harness governance (policies, audit, budget) |
| **Multi-agent orchestration** | `AgentMesh` with `@mesh.role` / `@mesh.orchestrator`, budget propagation, cycle detection |
| **Safety harness** | 8 policy types, static AST analysis, process sandbox, monitors, validators, audit trail |
| **Prompt-injection & PII** | `PromptInjectionPolicy` detects injection attacks; `PIIPolicy` + `redact_pii` catch and mask sensitive data |
| **Cost budgeting** | Pre-call enforcement via `BudgetPolicy` and `PricingRegistry` with 4 independent scopes |
| **Agent memory** | `MemoryStore` with SQLite and in-memory backends — persist facts, preferences, and conversation history |
| **Streaming** | `AgentStream` with SSE and NDJSON transports, mid-stream approval pauses, replay after completion |
| **Autonomy policy** | `AutonomyPolicy` with `EscalateWhen` rules for live escalation during agent execution |
| **Code cache** | `CodeCache` skips the LLM entirely when an identical intent has an approved cached answer |
| **Approval workflows** | Human-in-the-loop for sensitive operations with HTTP 202 + async resolve |
| **Authentication** | API key, Bearer token, Basic auth — per-endpoint, per-router, or app-wide |
| **Dependency injection** | FastAPI-style `Depends()` with sync/async generators, caching, route-level deps |
| **Custom responses** | `HTMLResult`, `PlainTextResult`, `FileResult`, or any Starlette `Response` subclass |
| **HTMX support** | `HtmxHeaders` auto-injection, `htmx_response_headers()`, partial page updates |
| **File handling** | Upload via multipart, download via `FileResult`, streaming responses |
| **MCP support** | Expose endpoints as MCP tools for Claude Desktop, Cursor, and other LLM clients |
| **Observability** | OpenTelemetry spans + Prometheus metrics + W3C trace propagation, graceful no-op when absent |
| **Eval harness** | Regression-test agent endpoints with deterministic assertion suites |
| **OpenAPI docs** | Auto-generated Swagger UI, ReDoc, and OpenAPI 3.1.0 schema |
| **ASGI-native** | Built on Starlette — runs with uvicorn, Daphne, Hypercorn |

**Current scale:** 141 source modules, ~26,700 lines of code, **1,520 tests**, 32 runnable examples, 86 public API exports.

---

## The Harness: Safety by Default

Every piece of LLM-generated code passes through a multi-layered safety pipeline before it executes:

```
Generated Code
  -> Policy Evaluation (Code, Data, Resource, Runtime, Budget, PromptInjection, PII)
  -> Static AST Analysis (forbidden imports, eval/exec, file I/O, getattr)
  -> Approval Check (human-in-the-loop for sensitive operations)
  -> Process Sandbox (isolated subprocess with timeout + resource limits)
  -> Post-Execution Monitors + Validators
  -> Audit Trail Recording (in-memory or SQLite-backed)
```

```python
from agenticapi import (
    CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy,
    BudgetPolicy, PricingRegistry, PromptInjectionPolicy, PIIPolicy,
)

CodePolicy(denied_modules=["os", "subprocess"], deny_eval_exec=True, max_code_lines=500)
DataPolicy(readable_tables=["orders"], deny_ddl=True)
ResourcePolicy(max_cpu_seconds=30, max_memory_mb=512)
RuntimePolicy(max_code_complexity=500)
BudgetPolicy(pricing=PricingRegistry.default(), max_per_request_usd=0.10)
PromptInjectionPolicy()     # detects injection attacks in user input
PIIPolicy()                  # catches email, phone, SSN patterns
```

See [example 22](./examples/22_safety_policies) for shadow mode, redact mode, and custom patterns. See [example 31](./examples/31_sandbox_and_guards) for the full defence-in-depth sandbox pipeline.

---

## Agentic Loop

The multi-turn agentic loop is the core of what makes AgenticAPI an *agent* framework. The LLM autonomously decides which tools to call, inspects intermediate results, and reasons step-by-step to a final answer — all under harness governance.

```python
from agenticapi import AgenticApp, tool, LoopConfig
from agenticapi.harness.engine import HarnessEngine
from agenticapi.runtime.tools.registry import ToolRegistry

@tool(description="Get current weather for a city")
async def get_weather(city: str) -> dict:
    return {"city": city, "temp": 22, "rain_pct": 80}

@tool(description="Get clothing advice")
async def get_clothing_advice(temp: int, is_raining: bool) -> str:
    return "Wear a waterproof jacket." if is_raining else "Light clothing is fine."

registry = ToolRegistry([get_weather, get_clothing_advice])

app = AgenticApp(
    title="Weather Advisor",
    llm=backend,
    harness=HarnessEngine(),
    tools=registry,
)

@app.agent_endpoint(name="advisor", loop_config=LoopConfig(max_iterations=5))
async def advisor(intent, context):
    return {}  # fallback — the agentic loop handles tool dispatch
```

What happens when a user asks *"Should I go out in Tokyo today?"*:

1. **Iteration 1:** LLM decides to call `get_weather("Tokyo")` -> `{temp: 22, rain_pct: 80}`
2. **Iteration 2:** LLM sees 80% rain, calls `get_clothing_advice(22, True)` -> `"Wear a waterproof jacket."`
3. **Iteration 3:** LLM returns: *"It's 22C with 80% chance of rain. Wear a waterproof jacket and carry an umbrella."*

Every tool call goes through `HarnessEngine.call_tool()` — policy-checked, audit-recorded, budget-tracked. See [example 29](./examples/29_agentic_loop).

You can also use the loop standalone:

```python
from agenticapi import run_agentic_loop, LoopConfig

result = await run_agentic_loop(
    llm=backend, tools=registry, harness=harness,
    prompt=prompt, config=LoopConfig(max_iterations=10),
)
print(result.final_text)           # "Wear a waterproof jacket..."
print(result.iterations)           # 3
print(result.tool_calls_made)      # [ToolCallRecord(...), ...]
```

---

## Workflow Engine

For multi-step processes that need conditional branching, parallel execution, or human-in-the-loop checkpoints, use the declarative workflow engine.

```python
from agenticapi import AgentWorkflow, WorkflowState, WorkflowContext

class AnalysisState(WorkflowState):
    document_text: str = ""
    summary: str = ""
    risk_level: str = "unknown"

workflow = AgentWorkflow(name="analysis", state_class=AnalysisState)

@workflow.step("parse")
async def parse(state: AnalysisState, ctx: WorkflowContext) -> str:
    state.document_text = await ctx.call_tool("extract_text", document_id="doc-1")
    return "analyze"

@workflow.step("analyze")
async def analyze(state: AnalysisState, ctx: WorkflowContext) -> str:
    state.summary = await ctx.llm_generate(f"Summarize: {state.document_text}")
    if "material risk" in state.summary.lower():
        state.risk_level = "high"
        return "review"      # human review for high-risk docs
    state.risk_level = "low"
    return "done"

@workflow.step("review", checkpoint=True)
async def review(state: AnalysisState, ctx: WorkflowContext) -> str:
    return "done"            # continues after human approval

@workflow.step("done")
async def done(state: AnalysisState, ctx: WorkflowContext) -> None:
    return None              # workflow complete

# Wire directly into an endpoint — the framework handles everything:
@app.agent_endpoint(name="analyze", workflow=workflow)
async def handler(intent, context):
    return {}  # fallback
```

Workflows support typed state, conditional routing, parallel execution (`return ["step_a", "step_b"]`), checkpoints, per-step retry and timeout, `SqliteWorkflowStore` for persistence, and `workflow.to_mermaid()` for graph export. See [example 30](./examples/30_agent_workflow).

---

## Agent Playground & Trace Inspector

Two self-hosted, zero-dependency debug UIs — no npm, no build step, no external services.

```python
app = AgenticApp(
    title="My Agent",
    playground_url="/_playground",   # agent chat + trace viewer
    trace_url="/_trace",             # trace search, diff, cost analytics
)
```

**Playground** (`/_playground`) — three-panel interface: Agent Chat | Execution Trace | Trace History. Select an endpoint, type an intent, see the response with a timeline of policy decisions, tool calls, and LLM costs.

**Trace Inspector** (`/_trace`) — production-grade trace analysis: filter by endpoint, status, tool, date range, or cost; compare two traces side-by-side; see per-tool cost breakdowns; export traces as JSON compliance reports.

Both are disabled by default in production (`playground_url=None`, `trace_url=None`).

---

## Multi-Agent Orchestration

Compose multiple agent roles into governed pipelines with `AgentMesh`. Budget, trace, and approval propagate across hops:

```python
from agenticapi import AgenticApp, AgentMesh

app = AgenticApp(title="Research Pipeline")
mesh = AgentMesh(app=app, name="research")

@mesh.role(name="researcher")
async def researcher(payload, ctx):
    return {"topic": payload, "points": ["finding 1", "finding 2"]}

@mesh.role(name="reviewer")
async def reviewer(payload, ctx):
    return {"approved": True, "feedback": "Looks good"}

@mesh.orchestrator(name="pipeline", roles=["researcher", "reviewer"], budget_usd=1.00)
async def pipeline(intent, mesh_ctx):
    research = await mesh_ctx.call("researcher", intent.raw)
    review = await mesh_ctx.call("reviewer", str(research))
    return {"research": research, "review": review}
```

The mesh provides in-process routing, budget propagation, cycle detection, and standalone endpoints for every role. See [example 27](./examples/27_multi_agent_pipeline).

---

## Native Function Calling

All LLM backends translate between the framework's generic tool format and each provider's native wire format — and parse responses into framework-standard `ToolCall` objects:

```python
from agenticapi import tool
from agenticapi.runtime.llm.base import LLMPrompt, LLMMessage

@tool(description="Look up current weather for a city")
async def get_weather(city: str) -> dict:
    return {"city": city, "temp": 22, "condition": "sunny"}

response = await backend.generate(
    LLMPrompt(
        system="You are a helpful assistant.",
        messages=[LLMMessage(role="user", content="What's the weather in Tokyo?")],
        tools=[{"name": "get_weather", "description": "...", "parameters": {...}}],
        tool_choice="auto",
    )
)

if response.finish_reason == "tool_calls":
    for call in response.tool_calls:
        print(f"Tool: {call.name}, Args: {call.arguments}")
```

Every backend retries on transient errors (rate limits, timeouts, 5xx) with configurable `RetryConfig`. See [example 19](./examples/19_native_function_calling).

---

## Harness-Governed MCP Tool Server

Expose your `@tool` functions as MCP tools with full harness governance — every call from Claude Code, Cursor, or any MCP client goes through your policies, audit trail, and budget controls:

```python
from agenticapi.mcp_tools import HarnessMCPServer

app = AgenticApp(harness=harness, tools=registry)
HarnessMCPServer(app, path="/mcp/tools")
```

When an AI assistant calls your tool via MCP:
1. `PromptInjectionPolicy` scans the arguments
2. `DataPolicy` verifies access permissions
3. The tool executes
4. `PIIPolicy` scans the result
5. `AuditRecorder` logs the call

Requires `pip install agentharnessapi[mcp]`. See [example 32](./examples/32_harness_mcp_tools).

---

## LLM Backends

| Backend | Provider | Env Variable | Function Calling | Retry |
|---|---|---|---|---|
| `AnthropicBackend` | Anthropic Claude | `ANTHROPIC_API_KEY` | `tool_use` blocks | RateLimitError, Timeout, 5xx |
| `OpenAIBackend` | OpenAI GPT | `OPENAI_API_KEY` | `tool_calls` on message | RateLimitError, Timeout |
| `GeminiBackend` | Google Gemini | `GOOGLE_API_KEY` | `function_call` parts | ResourceExhausted, Unavailable |
| `MockBackend` | (Testing) | -- | Queued `ToolCall` objects | -- |

All backends implement the `LLMBackend` protocol. Bring your own by implementing `generate()`, `generate_stream()`, and `model_name`.

---

## Tools

```python
from agenticapi import tool
from agenticapi.runtime.tools import ToolRegistry

@tool(description="Search the documentation index")
async def search_docs(query: str, limit: int = 10) -> list[dict]:
    return await index.search(query, limit=limit)

registry = ToolRegistry()
registry.register(search_docs)
```

The `@tool` decorator auto-generates the JSON schema from your type hints. See [example 14](./examples/14_dependency_injection) for the full pattern.

---

## Authentication

```python
from agenticapi.security import APIKeyHeader, Authenticator, AuthUser

api_key = APIKeyHeader(name="X-API-Key")

async def verify(credentials):
    if credentials.credentials == "secret-key":
        return AuthUser(user_id="user-1", username="alice", roles=("admin",))
    return None

auth = Authenticator(scheme=api_key, verify=verify)

@app.agent_endpoint(name="orders", auth=auth)
async def orders(intent, context):
    print(context.user_id)  # "user-1"
```

Available schemes: `APIKeyHeader`, `APIKeyQuery`, `HTTPBearer`, `HTTPBasic`. See [example 9](./examples/09_auth_agent).

---

## Streaming

Handlers can emit typed events over SSE or NDJSON, pause for mid-stream approval, and support replay:

```python
from agenticapi.interface.stream import AgentStream

@app.agent_endpoint(name="deploy", streaming="sse")
async def deploy(intent, context, stream: AgentStream):
    await stream.emit_thought("Checking deployment prerequisites...")
    await stream.emit_tool_call_started(call_id="c1", name="health_check")
    # ... do work ...
    decision = await stream.request_approval(prompt="Continue deploy?")
    await stream.emit_final(result={"status": "deployed"})
```

See [example 20](./examples/20_streaming_release_control) for SSE, NDJSON, resume, and replay.

---

## Cost Budgeting

`BudgetPolicy` enforces cost ceilings **before** the LLM call with 4 independent scopes (per-request, per-session, per-user-per-day, per-endpoint-per-day). When a request would exceed any limit the harness raises `BudgetExceeded` (HTTP 402) **before any tokens are spent**. See [example 15](./examples/15_budget_policy).

---

## Agent Memory

Agents can persist facts, preferences, and conversation history across sessions:

```python
from agenticapi import AgenticApp, SqliteMemoryStore

app = AgenticApp(
    title="Personal Assistant",
    memory=SqliteMemoryStore(path="./memory.sqlite"),
)
```

Memories are typed (`MemoryKind`: episodic, semantic, procedural) and scoped (per-user, per-session, global). See [example 21](./examples/21_persistent_memory).

---

## Custom Responses, HTMX & File Handling

```python
from agenticapi import HTMLResult, PlainTextResult, FileResult, HtmxHeaders

@app.agent_endpoint(name="dashboard")
async def dashboard(intent, context):
    return HTMLResult(content="<h1>Dashboard</h1>")

@app.agent_endpoint(name="items")
async def items(intent, context, htmx: HtmxHeaders):
    if htmx.is_htmx:
        return HTMLResult(content="<li>Item 1</li>")
    return HTMLResult(content="<html>Full page</html>")
```

File upload via multipart, download via `FileResult`, streaming via Starlette. See examples [10](./examples/10_file_handling), [11](./examples/11_html_responses), [12](./examples/12_htmx).

---

## MCP & REST Compatibility

```python
# Expose endpoints as MCP tools (pip install agentharnessapi[mcp])
from agenticapi.interface.compat.mcp import expose_as_mcp
expose_as_mcp(app, path="/mcp")

# Expose as REST GET/POST routes
from agenticapi.interface.compat import expose_as_rest
app.add_routes(expose_as_rest(app, prefix="/rest"))

# Starlette middleware
from starlette.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])
```

---

## Observability

Structured logging via structlog is on by default. OpenTelemetry tracing and Prometheus metrics are auto-detected:

```python
from agenticapi.observability import configure_tracing, configure_metrics

configure_tracing(service_name="my-service", otlp_endpoint="http://tempo:4317")
configure_metrics(service_name="my-service", enable_prometheus=True)
```

W3C trace propagation, request/latency/cost/denial metrics, graceful no-ops when not installed. See [example 16](./examples/16_observability).

---

## Extensions

Heavyweight integrations are released as separate packages:

```bash
pip install agentharnessapi[claude-agent-sdk]
```

```python
from agenticapi.ext.claude_agent_sdk import ClaudeAgentRunner

runner = ClaudeAgentRunner(
    system_prompt="You are a coding assistant.",
    allowed_tools=["Read", "Glob", "Grep"],
)

@app.agent_endpoint(name="assistant", autonomy_level="manual")
async def assistant(intent, context):
    return await runner.run(intent=intent, context=context)
```

See [example 13](./examples/13_claude_agent_sdk).

---

## Examples

Thirty-two example apps, from minimal hello-world to harness-governed MCP tool servers:

| # | Example | LLM | Highlights |
|---|---|---|---|
| 01 | [hello_agent](./examples/01_hello_agent) | -- | Minimal single endpoint |
| 02 | [ecommerce](./examples/02_ecommerce) | -- | Routers, policies, approval, tools |
| 03 | [openai_agent](./examples/03_openai_agent) | OpenAI | Full harness pipeline with GPT |
| 04 | [anthropic_agent](./examples/04_anthropic_agent) | Anthropic | Claude with `ResourcePolicy` |
| 05 | [gemini_agent](./examples/05_gemini_agent) | Gemini | Sessions and multi-turn |
| 06 | [full_stack](./examples/06_full_stack) | Configurable | Pipeline, ops, A2A, REST compat, monitors |
| 07 | [comprehensive](./examples/07_comprehensive) | Configurable | DevOps platform, multi-feature per endpoint |
| 08 | [mcp_agent](./examples/08_mcp_agent) | -- | MCP server with selective endpoint exposure |
| 09 | [auth_agent](./examples/09_auth_agent) | -- | API key auth with role-based access |
| 10 | [file_handling](./examples/10_file_handling) | -- | Upload, download, streaming |
| 11 | [html_responses](./examples/11_html_responses) | -- | HTML, plain text, custom responses |
| 12 | [htmx](./examples/12_htmx) | -- | Interactive todo app with partial updates |
| 13 | [claude_agent_sdk](./examples/13_claude_agent_sdk) | Extension | Full Claude Agent SDK loop |
| 14 | [dependency_injection](./examples/14_dependency_injection) | -- | Bookstore with every `Depends()` pattern |
| 15 | [budget_policy](./examples/15_budget_policy) | Mock | Cost governance, 4 budget scopes |
| 16 | [observability](./examples/16_observability) | -- | OTel tracing, Prometheus, SQLite audit |
| 17 | [typed_intents](./examples/17_typed_intents) | Mock | `Intent[T]` with Pydantic schemas |
| 18 | [rest_interop](./examples/18_rest_interop) | -- | `response_model`, `expose_as_rest`, mounted sub-app |
| 19 | [native_function_calling](./examples/19_native_function_calling) | Mock | `ToolCall` dispatch, multi-turn loop |
| 20 | [streaming_release_control](./examples/20_streaming_release_control) | -- | SSE, NDJSON, approval resume, replay |
| 21 | [persistent_memory](./examples/21_persistent_memory) | -- | Agent memory with SQLite persistence |
| 22 | [safety_policies](./examples/22_safety_policies) | -- | Prompt-injection detection, PII protection |
| 23 | [eval_harness](./examples/23_eval_harness) | -- | Regression-test agent endpoints |
| 24 | [code_cache](./examples/24_code_cache) | -- | Skip LLM with approved-code cache |
| 25 | [harness_playground](./examples/25_harness_playground) | -- | Full harness with autonomy, safety, streaming |
| 26 | [dynamic_pipeline](./examples/26_dynamic_pipeline) | -- | Middleware-like stage composition |
| 27 | [multi_agent_pipeline](./examples/27_multi_agent_pipeline) | -- | 3-role `AgentMesh` with budget propagation |
| 28 | [sessions_and_tasks](./examples/28_sessions_and_tasks) | -- | Multi-turn sessions, background tasks, 4 auth schemes |
| 29 | [agentic_loop](./examples/29_agentic_loop) | Mock | Multi-turn ReAct loop with autonomous tool selection |
| 30 | [agent_workflow](./examples/30_agent_workflow) | -- | Declarative workflow with branching and checkpoints |
| 31 | [sandbox_and_guards](./examples/31_sandbox_and_guards) | -- | Defence-in-depth: static analysis, sandbox, monitors, validators |
| 32 | [harness_mcp_tools](./examples/32_harness_mcp_tools) | -- | Harness-governed MCP tool server for AI assistants |

Every example is a standalone ASGI app — `agenticapi dev --app examples.NN_name.app:app` and you're running. See the [examples README](./examples/README.md) for curl commands and per-endpoint documentation.

---

## CLI Reference

```bash
agenticapi init <name> [--template default|chat|tool-calling]  # Scaffold a new project
agenticapi dev --app myapp:app [--host 0.0.0.0] [--port 8000]  # Development server
agenticapi console --app myapp:app                              # Interactive REPL
agenticapi replay <trace_id> --app myapp:app                    # Re-run audit trace
agenticapi eval --set evals/golden.yaml --app myapp:app         # Regression gate
agenticapi version                                              # Show version
```

---

## Development

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
uv sync --group dev
```

### Running Tests

```bash
uv run pytest                                # All 1,520 tests
uv run pytest tests/unit/ -xvs              # Unit tests, stop on first failure
uv run pytest tests/e2e/ -v                 # E2E tests for all 32 examples
uv run pytest -m "not requires_llm"         # Skip tests needing API keys
uv run pytest --cov=src/agenticapi          # With coverage
```

### Code Quality

```bash
uv run ruff format src/ tests/ examples/    # Format
uv run ruff check src/ tests/ examples/     # Lint
uv run mypy src/agenticapi/                 # Type check (strict mode)
```

### Pre-commit Hooks

```bash
pip install pre-commit && pre-commit install
```

---

## Project Structure

```
src/agenticapi/
    __init__.py             # 86 public exports
    app.py                  # AgenticApp — main ASGI application
    routing.py              # AgentRouter — endpoint grouping
    security.py             # Authentication (APIKeyHeader, HTTPBearer, Authenticator)
    exceptions.py           # Exception hierarchy with HTTP status mapping
    openapi.py              # OpenAPI schema, Swagger UI, ReDoc
    types.py                # AutonomyLevel, Severity, TraceLevel
    dependencies/           # Depends(), InjectionPlan, solver
    interface/
        intent.py           # Intent, Intent[T], IntentParser, IntentScope
        response.py         # AgentResponse, FileResult, HTMLResult, PlainTextResult
        stream.py           # AgentStream, typed event types (SSE/NDJSON streaming)
        upload.py           # UploadFile, UploadedFiles
        htmx.py             # HtmxHeaders, htmx_response_headers
        compat/             # REST, FastAPI, MCP compatibility
    harness/
        engine.py           # HarnessEngine — safety pipeline orchestrator
        policy/             # Code, Data, Resource, Runtime, Budget, PromptInjection, PII, Autonomy
        sandbox/            # ProcessSandbox, static AST analysis, monitors, validators
        approval/           # ApprovalWorkflow, ApprovalRule
        audit/              # AuditRecorder, SqliteAuditRecorder, ExecutionTrace
    runtime/
        loop.py             # run_agentic_loop — multi-turn ReAct pattern
        code_generator.py   # LLM-powered code generation
        code_cache.py       # CodeCache, InMemoryCodeCache
        context.py          # AgentContext, ContextWindow
        memory/             # MemoryStore, SqliteMemoryStore, InMemoryMemoryStore
        llm/                # Anthropic, OpenAI, Gemini, Mock — with ToolCall + RetryConfig
        tools/              # ToolRegistry, @tool decorator, built-in tools
    workflow/               # AgentWorkflow, WorkflowState, WorkflowStore
    mesh/                   # AgentMesh, MeshContext — multi-agent orchestration
    mcp_tools/              # HarnessMCPServer — governed MCP tool dispatch
    playground/             # /_playground debugger UI
    trace_inspector/        # /_trace inspection UI with search, diff, analytics
    observability/          # OpenTelemetry tracing, Prometheus metrics, W3C propagation
    evaluation/             # EvalSet, judges, runner
    cli/                    # dev, console, replay, eval, init, version

examples/
    01_hello_agent/ .. 32_harness_mcp_tools/   # 32 runnable example apps
```

---

## Requirements

- **Python** >= 3.13
- **[Starlette](https://www.starlette.io/)** >= 1.0 — ASGI foundation
- **[Pydantic](https://docs.pydantic.dev/)** >= 2.12 — Validation and schemas
- **[structlog](https://www.structlog.org/)** >= 25.0 — Structured logging
- **[httpx](https://www.python-httpx.org/)** >= 0.28 — Async HTTP client
- **[python-multipart](https://github.com/Kludex/python-multipart)** >= 0.0.20 — File upload parsing
- LLM SDKs: [anthropic](https://github.com/anthropics/anthropic-sdk-python) >= 0.89, [openai](https://github.com/openai/openai-python) >= 2.30, [google-genai](https://github.com/googleapis/python-genai) >= 1.70

Everything else (OpenTelemetry, Prometheus, MCP) is optional and degrades gracefully when absent.

---

## Documentation

Full documentation lives at [`docs/`](./docs/) and is published with MkDocs:

```bash
mkdocs serve -a 127.0.0.1:8001   # Live-reloading docs
```

- **[Getting Started](./docs/getting-started/)** — Installation, quick start, all 32 examples
- **[Guides](./docs/guides/)** — Architecture, typed intents, DI, safety policies, streaming, memory, eval harness, observability, and more
- **[API Reference](./docs/api/)** — Every public class and function
- **[Internals](./docs/internals/)** — Module reference, extending the framework, implementation notes

### Where everything lives

| File | Purpose |
|---|---|
| [`PROJECT.md`](./PROJECT.md) | Stable product vision, design principles, architecture pillars |
| [`CLAUDE.md`](./CLAUDE.md) | Developer guide — commands, conventions, module map |
| [`ROADMAP.md`](./ROADMAP.md) | Living status — shipped / active / deferred tables |
| [`VISION.md`](./VISION.md) | Speculative forward tracks (Trust, Flywheel) |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Contributor onboarding |

---

## Contributing

Contributions are very welcome! See [CONTRIBUTING.md](./CONTRIBUTING.md) for setup, code conventions, and the PR workflow. If you're not sure where to start, a new example app or an improvement to an existing one is always a great first PR.

Found a bug or have an idea? [Open an issue](https://github.com/shibuiwilliam/AgenticAPI/issues) — we'd love to hear from you.

## License

[Apache 2.0](./LICENSE)
