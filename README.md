# AgenticAPI

**The agent-native web framework for Python.** Build APIs where endpoints understand natural language, generate code on the fly, and execute it safely behind a multi-layered harness -- all with the developer ergonomics you know from FastAPI.

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Tests](https://img.shields.io/badge/tests-1310%20passing-brightgreen.svg)]()
[![Examples](https://img.shields.io/badge/examples-27%20runnable-blueviolet.svg)](./examples)

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

You instantly get Swagger UI at `/docs`, ReDoc at `/redoc`, an OpenAPI 3.1 spec at `/openapi.json`, and `/health` + `/capabilities` endpoints -- no extra wiring.

---

## Table of Contents

- [Why AgenticAPI?](#why-agenticapi)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Quick Tour](#quick-tour)
- [How It Maps to FastAPI](#how-it-maps-to-fastapi)
- [Features at a Glance](#features-at-a-glance)
- [Safety: The Harness System](#safety-the-harness-system)
- [Native Function Calling](#native-function-calling)
- [Multi-Agent Orchestration](#multi-agent-orchestration)
- [Authentication](#authentication)
- [LLM Backends](#llm-backends)
- [Tools](#tools)
- [Custom Responses, HTMX & File Handling](#custom-responses-htmx--file-handling)
- [MCP, REST Compatibility & Middleware](#mcp-rest-compatibility--middleware)
- [Observability](#observability)
- [Extensions](#extensions)
- [Examples](#examples)
- [CLI Reference](#cli-reference)
- [Development](#development)
- [Project Structure](#project-structure)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Why AgenticAPI?

> **FastAPI is for type-safe REST APIs. AgenticAPI is for harnessed agent APIs.**

Traditional web frameworks expect structured request bodies. AgenticAPI endpoints accept natural-language **intents** instead. Under the hood an LLM can parse those intents into Pydantic schemas, choose tools via native function calling, or even generate Python code -- and a multi-layered **harness** evaluates, sandboxes, budgets, and audits every execution before it ever touches your data.

The best part: **you can use it with or without an LLM.**

- **Without an LLM** -- a clean decorator-based ASGI framework with FastAPI-like ergonomics: dependency injection, `response_model` validation, authentication, OpenAPI docs, HTMX support, file upload/download, streaming (SSE + NDJSON), background tasks, and more.
- **With an LLM** -- a complete agent execution platform: typed structured outputs, native function calling across Anthropic/OpenAI/Gemini with retry and backoff, policy enforcement (code, data, resources, budget, prompt-injection, PII), AST analysis, process sandboxing, approval workflows, persistent audit trails, agent memory, code caching, autonomy escalation, multi-agent orchestration, and full observability.

Either way you get **27 runnable examples** to copy from, **1,310 passing tests** that prove every feature works, and a production-ready observability story (OpenTelemetry spans, Prometheus metrics, W3C trace propagation -- all optional, all graceful no-ops when unused).

---

## Installation

**Python 3.13+** is required. The framework uses `match`, `type` aliases, `StrEnum`, and other modern features.

```bash
pip install agenticapi
```

For development:

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
uv sync --group dev    # or: pip install -e ".[dev]"
```

Optional extras:

```bash
pip install agenticapi[mcp]                  # MCP server support
pip install agenticapi-claude-agent-sdk      # Full Claude Agent SDK loop (separate package)

# Observability -- all optional, all graceful no-ops when missing
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

This generates a ready-to-run project with a handler, tools, harness, and an eval set -- all wired together. It works immediately with `MockBackend` (no API key needed). Set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY` to switch to a real provider.

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

Add an LLM backend and harness engine to generate and safely execute code from natural language:

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

Constrain the LLM's output to a Pydantic schema -- full validation before the handler runs:

```python
from pydantic import BaseModel, Field
from agenticapi import Intent

class OrderSearch(BaseModel):
    status: str | None = None
    limit: int = Field(default=10, ge=1, le=100)

@app.agent_endpoint(name="orders.search")
async def search(intent: Intent[OrderSearch], context):
    query = intent.params  # already validated, fully typed, autocomplete works
    return {"status": query.status, "limit": query.limit}
```

See [example 17](./examples/17_typed_intents) for the full pattern.

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

See [example 14](./examples/14_dependency_injection) for nested deps, route-level deps, and `@tool`.

### 5. Programmatic usage (no HTTP)

```python
response = await app.process_intent(
    "Show me last month's orders",
    endpoint_name="orders.query",
    session_id="session-123",
)
print(response.result)
print(response.generated_code)
print(response.reasoning)
```

---

## How It Maps to FastAPI

If you know FastAPI, you already know the patterns:

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
| **Typed intents** | Constrain LLM output to a Pydantic schema with `Intent[T]` -- full validation, IDE autocompletion |
| **Multi-LLM** | Anthropic Claude, OpenAI GPT, Google Gemini, deterministic Mock -- swap with one line |
| **Native function calling** | First-class `ToolCall` + `finish_reason` + `tool_choice` across every backend, with retry and backoff |
| **Multi-agent orchestration** | `AgentMesh` with `@mesh.role` / `@mesh.orchestrator`, budget propagation, cycle detection |
| **Safety harness** | 8 policy types, static AST analysis, process sandbox, monitors, validators, audit trail |
| **Prompt-injection & PII** | `PromptInjectionPolicy` detects injection attacks; `PIIPolicy` + `redact_pii` catch and mask sensitive data |
| **Persistent audit** | In-memory for dev or `SqliteAuditRecorder` for production -- stdlib only, zero new deps |
| **Cost budgeting** | Pre-call enforcement via `BudgetPolicy` and `PricingRegistry` with 4 independent scopes |
| **Agent memory** | `MemoryStore` with SQLite and in-memory backends -- persist facts, preferences, and conversation history |
| **Code cache** | `CodeCache` skips the LLM entirely when an identical intent has an approved cached answer |
| **Streaming** | `AgentStream` with SSE and NDJSON transports, mid-stream approval pauses, replay after completion |
| **Autonomy policy** | `AutonomyPolicy` with `EscalateWhen` rules for live escalation during agent execution |
| **Approval workflows** | Human-in-the-loop for sensitive operations with HTTP 202 + async resolve |
| **Authentication** | API key, Bearer token, Basic auth -- per-endpoint, per-router, or app-wide |
| **Dependency injection** | FastAPI-style `Depends()` with sync/async generators, caching, route-level deps |
| **Response validation** | Pydantic `response_model` validates handler returns and publishes the schema in OpenAPI |
| **Custom responses** | `HTMLResult`, `PlainTextResult`, `FileResult`, or any Starlette `Response` subclass |
| **HTMX support** | `HtmxHeaders` auto-injection, `htmx_response_headers()`, partial page updates |
| **File handling** | Upload via multipart, download via `FileResult`, streaming responses |
| **MCP support** | Expose endpoints as MCP tools for Claude Desktop, Cursor, and other LLM clients |
| **`@tool` decorator** | Turn plain functions into registered tools with auto-generated JSON schemas |
| **Project scaffolding** | `agenticapi init` generates a ready-to-run project with tools, harness, and evals |
| **Background tasks** | `AgentTasks` for post-response work (like FastAPI's `BackgroundTasks`) |
| **Middleware** | Full Starlette middleware (CORS, compression, custom) |
| **Dynamic pipelines** | Agent-level processing stages composed at runtime |
| **Agent-to-Agent** | Capability discovery, trust scoring, inter-agent communication |
| **Sessions** | Multi-turn conversations with context accumulation and TTL expiration |
| **REST compatibility** | Mount FastAPI inside AgenticAPI, or expose agent endpoints as REST routes |
| **Extensions** | Independent packages like `agenticapi-claude-agent-sdk` for heavyweight integrations |
| **Observability** | OpenTelemetry spans + Prometheus metrics + W3C trace propagation, graceful no-op when absent |
| **Eval harness** | Regression-test agent endpoints with deterministic assertion suites |
| **OpenAPI docs** | Auto-generated Swagger UI, ReDoc, and OpenAPI 3.1.0 schema |
| **ASGI-native** | Built on Starlette -- runs with uvicorn, Daphne, Hypercorn |

**Current scale:** 118 source modules, ~25,000 lines of code, **1,310 tests** (+38 in extensions), 27 runnable examples, 1 published extension.

---

## Safety: The Harness System

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

### Policies

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
PromptInjectionPolicy()          # detects injection attacks in user input
PIIPolicy()                       # catches email, phone, SSN patterns
```

### Agent Memory

Agents can persist facts, preferences, and conversation history across sessions:

```python
from agenticapi import AgenticApp, SqliteMemoryStore

app = AgenticApp(
    title="Personal Assistant",
    memory=SqliteMemoryStore(path="./memory.sqlite"),
)
```

Memories are typed (`MemoryKind`: fact, preference, conversation, system) and stored with timestamps for retrieval and relevance scoring. See [example 21](./examples/21_persistent_memory).

### Code Cache

Skip the LLM entirely when an identical intent already has an approved answer:

```python
from agenticapi import AgenticApp, InMemoryCodeCache

app = AgenticApp(title="Cached Agent", code_cache=InMemoryCodeCache())
```

See [example 24](./examples/24_code_cache).

### Streaming

Handlers can emit events over SSE or NDJSON, pause for mid-stream approval, and support replay after completion:

```python
@app.agent_endpoint(name="deploy", streaming="sse")
async def deploy(intent, context, stream: AgentStream):
    await stream.emit(AgentEvent(kind="progress", data={"step": 1}))
    decision = await stream.request_approval(reason="Continue deploy?")
    await stream.emit(AgentEvent(kind="complete", data={"approved": decision}))
    return {"status": "deployed"}
```

See [example 20](./examples/20_streaming_release_control) for the full pattern with SSE, NDJSON, resume, and replay routes.

### Cost Budgeting

`BudgetPolicy` enforces cost ceilings **before** the LLM call with 4 independent scopes (per-request, per-session, per-user-per-day, per-endpoint-per-day). When a request would exceed any limit the harness raises `BudgetExceeded` (HTTP 402) **before any tokens are spent**. See [example 15](./examples/15_budget_policy).

### Sandbox & Audit

Generated code runs in an isolated subprocess with timeout, resource metrics, and stdout/stderr capture. Every execution is recorded as an `ExecutionTrace`. Choose `InMemoryAuditRecorder` for dev or `SqliteAuditRecorder` for production -- zero new dependencies (stdlib `sqlite3`). See [example 16](./examples/16_observability).

---

## Native Function Calling

All three LLM backends support native function calling with automatic retry and exponential backoff:

```python
from agenticapi import tool
from agenticapi.runtime.tools import ToolRegistry
from agenticapi.runtime.llm import AnthropicBackend, LLMPrompt, LLMMessage

@tool(description="Look up current weather for a city")
async def get_weather(city: str) -> dict:
    return {"city": city, "temp": 22, "condition": "sunny"}

# The LLM decides when to call tools -- you get structured ToolCall objects back
backend = AnthropicBackend()  # also OpenAIBackend(), GeminiBackend()
response = await backend.generate(
    LLMPrompt(
        system="You are a helpful assistant.",
        messages=[LLMMessage(role="user", content="What's the weather in Tokyo?")],
        tools=[get_weather.tool.definition.to_dict()],
        tool_choice="auto",  # "auto", "required", "none", or {"type": "tool", "name": "..."}
    )
)

if response.finish_reason == "tool_calls":
    for call in response.tool_calls:
        print(f"Tool: {call.name}, Args: {call.arguments}")
```

Every backend automatically retries on transient errors (rate limits, timeouts, 5xx) with configurable `RetryConfig`. See [example 19](./examples/19_native_function_calling) for a multi-turn tool-use loop.

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

```bash
curl -X POST http://localhost:8000/agent/pipeline \
  -H "Content-Type: application/json" \
  -d '{"intent": "quantum computing"}'
```

The mesh provides:
- **In-process routing** -- `MeshContext.call()` resolves roles locally (no HTTP overhead)
- **Budget propagation** -- sub-agent calls debit the orchestrator's ceiling
- **Cycle detection** -- role A calling role B calling role A raises `MeshCycleError`
- **Standalone endpoints** -- every role is also exposed at `/agent/{role_name}`

See [example 27](./examples/27_multi_agent_pipeline) for a 3-role research pipeline.

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

## LLM Backends

| Backend | Provider | Default Model | Env Variable | Function Calling | Retry |
|---|---|---|---|---|---|
| `AnthropicBackend` | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | `tool_use` blocks | RateLimitError, Timeout, 5xx |
| `OpenAIBackend` | OpenAI | `gpt-5.4-mini` | `OPENAI_API_KEY` | `tool_calls` on message | RateLimitError, Timeout |
| `GeminiBackend` | Google | `gemini-2.5-flash` | `GOOGLE_API_KEY` | `function_call` parts | ResourceExhausted, Unavailable |
| `MockBackend` | (Testing) | `mock` | -- | Queued `ToolCall` objects | -- |

All backends implement the `LLMBackend` protocol and return `LLMResponse` with populated `tool_calls`, `finish_reason`, and `usage`. Bring your own by implementing `generate()`, `generate_stream()`, and `model_name`.

---

## Tools

Four built-in tools plus a `@tool` decorator for plain functions:

```python
from agenticapi import tool
from agenticapi.runtime.tools import ToolRegistry, DatabaseTool, CacheTool

@tool(description="Search the documentation index")
async def search_docs(query: str, limit: int = 10) -> list[dict]:
    return await index.search(query, limit=limit)

registry = ToolRegistry()
registry.register(search_docs)
registry.register(DatabaseTool(name="db", execute_fn=my_query_fn, read_only=True))
```

The `@tool` decorator auto-generates the JSON schema from your type hints and infers capabilities from the function name. See [example 19](./examples/19_native_function_calling) for the native function-calling pattern with a multi-turn tool-use loop.

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
        return HTMLResult(content="<li>Item 1</li>")     # Fragment
    return HTMLResult(content="<html>Full page</html>")   # Full page
```

File upload via multipart, download via `FileResult`, streaming via Starlette. See examples [10](./examples/10_file_handling), [11](./examples/11_html_responses), [12](./examples/12_htmx).

---

## MCP, REST Compatibility & Middleware

```python
# Expose endpoints as MCP tools (pip install agenticapi[mcp])
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

Structured logging via structlog is on by default. OpenTelemetry tracing and Prometheus metrics are auto-detected -- install the packages and call `configure_tracing()` / `configure_metrics()`:

```python
from agenticapi.observability import configure_tracing, configure_metrics

configure_tracing(service_name="my-service", otlp_endpoint="http://tempo:4317")
configure_metrics(service_name="my-service", enable_prometheus=True)
```

W3C trace propagation, request/latency/cost/denial metrics, graceful no-ops when not installed. See [example 16](./examples/16_observability).

---

## Extensions

Heavyweight integrations are released as separate packages under `extensions/`:

```bash
pip install agenticapi-claude-agent-sdk
```

```python
from agenticapi_claude_agent_sdk import ClaudeAgentRunner

runner = ClaudeAgentRunner(
    system_prompt="You are a coding assistant.",
    allowed_tools=["Read", "Glob", "Grep"],
    policies=[CodePolicy(denied_modules=["os", "subprocess"])],
)

@app.agent_endpoint(name="assistant", autonomy_level="manual")
async def assistant(intent, context):
    return await runner.run(intent=intent, context=context)
```

See [example 13](./examples/13_claude_agent_sdk).

---

## Examples

Twenty-seven example apps, from minimal hello-world to multi-agent pipelines with budget propagation:

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

Every example is a standalone ASGI app -- `agenticapi dev --app examples.NN_name.app:app` and you're running. See the [examples README](./examples/README.md) for curl commands and per-endpoint documentation.

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

### Common Commands

```bash
make test          # Run all 1,310 tests
make test-cov      # Tests with coverage
make check         # Format + lint + typecheck
make fix           # Auto-fix formatting and lint issues
make dev           # Start dev server (hello agent example)
make docs          # Live-reloading documentation
```

### Running Tests

```bash
uv run pytest                                # All tests
uv run pytest tests/unit/ -xvs              # Unit tests, stop on first failure
uv run pytest tests/e2e/ -v                 # E2E tests for all 27 examples
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

Hooks run `ruff format`, `ruff check`, and `mypy` automatically before each commit.

---

## Project Structure

```
src/agenticapi/
    __init__.py             # 73 public exports
    app.py                  # AgenticApp -- main ASGI application
    routing.py              # AgentRouter -- endpoint grouping
    security.py             # Authentication (APIKeyHeader, HTTPBearer, Authenticator)
    exceptions.py           # Exception hierarchy with HTTP status mapping
    openapi.py              # OpenAPI schema, Swagger UI, ReDoc
    types.py                # AutonomyLevel, Severity, TraceLevel
    dependencies/           # Depends(), InjectionPlan, solver
    interface/
        intent.py           # Intent, Intent[T], IntentParser, IntentScope
        response.py         # AgentResponse, FileResult, HTMLResult, PlainTextResult
        stream.py           # AgentStream, AgentEvent -- SSE/NDJSON streaming
        stream_store.py     # Replayable event storage
        upload.py           # UploadFile, UploadedFiles
        htmx.py             # HtmxHeaders, htmx_response_headers
        tasks.py            # AgentTasks (background tasks)
        session.py          # SessionManager with TTL
        transports/         # SSE and NDJSON framing helpers
        compat/             # REST, FastAPI, MCP compatibility
        a2a/                # Agent-to-Agent protocol, capability, trust
    harness/
        engine.py           # HarnessEngine -- safety pipeline orchestrator
        policy/             # Code, Data, Resource, Runtime, Budget, PromptInjection, PII, Autonomy
        sandbox/            # ProcessSandbox, static AST analysis, monitors, validators
        approval/           # ApprovalWorkflow, ApprovalRule
        audit/              # AuditRecorder, SqliteAuditRecorder, ExecutionTrace
    runtime/
        code_generator.py   # LLM-powered code generation
        code_cache.py       # CodeCache, InMemoryCodeCache, CachedCode
        context.py          # AgentContext, ContextWindow
        memory/             # MemoryStore, SqliteMemoryStore, InMemoryMemoryStore
        llm/                # Anthropic, OpenAI, Gemini, Mock -- with ToolCall + RetryConfig
        tools/              # Database, Cache, HTTP, Queue, @tool decorator
        prompts/            # Prompt templates
    mesh/                   # AgentMesh, MeshContext -- multi-agent orchestration
    observability/          # OpenTelemetry tracing, Prometheus metrics, W3C propagation
    evaluation/             # EvalSet, judges, runner
    application/            # DynamicPipeline
    ops/                    # OpsAgent, OpsHealthStatus
    testing/                # mock_llm, MockSandbox, assertions, fixtures
    cli/                    # dev, console, replay, eval, init, version

extensions/
    agenticapi-claude-agent-sdk/   # Independent package -- full Claude Agent SDK loop

examples/
    01_hello_agent/ .. 27_multi_agent_pipeline/   # 27 runnable example apps
```

---

## Requirements

- **Python** >= 3.13
- **[Starlette](https://www.starlette.io/)** >= 1.0 -- ASGI foundation
- **[Pydantic](https://docs.pydantic.dev/)** >= 2.12 -- Validation and schemas
- **[structlog](https://www.structlog.org/)** >= 25.0 -- Structured logging
- **[httpx](https://www.python-httpx.org/)** >= 0.28 -- Async HTTP client
- **[python-multipart](https://github.com/Kludex/python-multipart)** >= 0.0.20 -- File upload parsing
- LLM SDKs: [anthropic](https://github.com/anthropics/anthropic-sdk-python) >= 0.89, [openai](https://github.com/openai/openai-python) >= 2.30, [google-genai](https://github.com/googleapis/python-genai) >= 1.70

Everything else (OpenTelemetry, Prometheus, MCP) is optional and degrades gracefully to a no-op when absent.

---

## Documentation

Full documentation lives at [`docs/`](./docs/) and is published with MkDocs:

```bash
make docs    # Live-reloading docs at http://127.0.0.1:8001
```

- **[Getting Started](./docs/getting-started/)** -- Installation, quick start, all 27 examples
- **[Guides](./docs/guides/)** -- Architecture, typed intents, DI, safety policies, streaming, memory, eval harness, observability, and more
- **[API Reference](./docs/api/)** -- Every public class and function
- **[Internals](./docs/internals/)** -- Module reference, extending the framework, implementation notes

### Where everything lives

| File | Purpose |
|---|---|
| [`PROJECT.md`](./PROJECT.md) | Stable product vision, design principles, architecture pillars |
| [`ROADMAP.md`](./ROADMAP.md) | Single source of execution truth -- shipped / active / deferred |
| [`VISION.md`](./VISION.md) | Speculative forward tracks (Agent Mesh, Hardened Trust, Self-Improving Flywheel) |
| [`CLAUDE.md`](./CLAUDE.md) | Developer guide -- commands, conventions, module map |
| [`IMPLEMENTATION_LOG.md`](./IMPLEMENTATION_LOG.md) | Append-only log of shipped increments |
| [`CONTRIBUTING.md`](./CONTRIBUTING.md) | Contributor onboarding |
| [`SECURITY.md`](./SECURITY.md) | Vulnerability reporting |

---

## Contributing

Contributions are very welcome! See [CONTRIBUTING.md](./CONTRIBUTING.md) for setup, code conventions, and the PR workflow. If you're not sure where to start, a new example app or an improvement to an existing one is always a great first PR.

Found a bug or have an idea? [Open an issue](https://github.com/shibuiwilliam/AgenticAPI/issues) -- we'd love to hear from you.

## License

[MIT](./LICENSE)
