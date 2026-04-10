# AgenticAPI

**The agent-native web framework for Python.** Build APIs whose endpoints
understand natural language, generate code on the fly, and execute it
safely behind a multi-layered harness.

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Tests](https://img.shields.io/badge/tests-740%20collected-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-89%25-brightgreen.svg)]()
[![mypy strict](https://img.shields.io/badge/mypy-strict-blue.svg)]()

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
uvicorn myapp:app --reload
curl -X POST http://127.0.0.1:8000/agent/greeter \
    -H 'content-type: application/json' \
    -d '{"intent": "Hello, how are you?"}'
```

That's it. You also get Swagger UI at `/docs`, ReDoc at `/redoc`, capability
discovery at `/capabilities`, and a health probe at `/health` — all
auto-generated.

---

## Table of contents

- [Why AgenticAPI?](#why-agenticapi)
- [Features at a glance](#features-at-a-glance)
- [Installation](#installation)
- [Five-minute tour](#five-minute-tour)
- [How it maps to FastAPI](#how-it-maps-to-fastapi)
- [The harness: making LLM code safe](#the-harness-making-llm-code-safe)
- [Authentication](#authentication)
- [Custom responses and HTMX](#custom-responses-and-htmx)
- [File upload and download](#file-upload-and-download)
- [LLM backends](#llm-backends)
- [Tools](#tools)
- [Background tasks](#background-tasks)
- [Sessions](#sessions)
- [MCP support](#mcp-support)
- [REST and FastAPI compatibility](#rest-and-fastapi-compatibility)
- [Extensions](#extensions)
- [Examples](#examples)
- [Development](#development)
- [Project layout](#project-layout)
- [Requirements](#requirements)
- [License](#license)

---

## Why AgenticAPI?

AgenticAPI is **FastAPI for AI agents**. Where FastAPI helps you build
type-safe REST APIs, AgenticAPI helps you build **agent-powered APIs** with
safety guardrails baked into the framework itself.

The key idea: instead of accepting structured JSON requests, your endpoints
accept *natural-language intents*. Behind each endpoint, an LLM can generate
Python code to fulfil the intent, and a multi-layered harness evaluates,
sandboxes, and audits every execution before it touches your data.

You can use the framework at any level of ambition:

- **No LLM at all?** It's a slim, decorator-based ASGI framework with
  Pydantic-friendly responses, file handling, auth, and HTMX support. Use
  it like a Python web framework with extra ergonomics.
- **Add an LLM?** It becomes an intent parser plus typed response builder
  on top of a Starlette app.
- **Add the harness?** Now it's a full agentic execution platform that
  generates code, evaluates it against declarative policies, runs it in
  an isolated subprocess sandbox, and records every step for audit.

The harness is the unique part. **You decide** what the agent is allowed
to do — which modules it can import, which tables it can read, how much
CPU and memory it gets, which operations require human approval — and the
framework enforces it on every request.

---

## Features at a glance

| Category | What you get |
|---|---|
| **Agent endpoints** | Decorator registration, natural-language intents, routers with prefixes and tags |
| **Multi-LLM** | Anthropic Claude, OpenAI GPT, Google Gemini, Mock — swap with one line, or bring your own |
| **Safety harness** | Code policies, data policies, resource limits, AST static analysis, process sandbox |
| **Approval workflows** | Declarative rules for human-in-the-loop approval of sensitive operations |
| **Authentication** | API key (header / query), Bearer token, Basic auth — per-endpoint or app-wide |
| **File handling** | Upload via `multipart/form-data` (50 MB/file), download via `FileResult`, streaming |
| **Custom responses** | `HTMLResult`, `PlainTextResult`, `FileResult`, or any Starlette `Response` subclass |
| **HTMX support** | `HtmxHeaders` auto-injection, `htmx_response_headers()`, fragment responses |
| **MCP support** | Expose endpoints as Model Context Protocol tools for Claude Desktop, Cursor, etc. |
| **OpenAPI docs** | Auto-generated Swagger UI, ReDoc, and OpenAPI 3.1.0 schema |
| **Background tasks** | `AgentTasks` for post-response work — like FastAPI's `BackgroundTasks` |
| **Middleware** | Full Starlette middleware stack (CORS, GZip, custom) |
| **Dynamic pipelines** | Agent-level processing stages composed at runtime |
| **Agent-to-Agent** | Capability discovery, trust scoring, inter-agent communication primitives |
| **Ops agents** | Autonomous monitoring with severity-based autonomy gating |
| **REST compatibility** | Mount FastAPI apps inside, or expose agent endpoints as REST GET/POST routes |
| **Sessions** | Multi-turn conversations with context accumulation and TTL expiration |
| **Observability** | Structured logging via `structlog`, execution traces, bounded audit records |
| **Extensions** | Independently installable add-ons under `extensions/`, starting with the Claude Agent SDK |
| **Type safety** | `mypy --strict` clean, ships a `py.typed` marker |
| **ASGI-native** | Built on Starlette — works with `uvicorn`, Daphne, Hypercorn |

---

## Installation

**Python 3.13 or newer** is required.

```bash
pip install agenticapi
```

Optional extras:

```bash
pip install agenticapi[mcp]                # MCP server support
pip install agenticapi-claude-agent-sdk    # Claude Agent SDK extension
```

For development:

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
uv sync --group dev
```

---

## Five-minute tour

### 1. The simplest possible endpoint (no LLM needed)

```python
from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="My Service")

@app.agent_endpoint(name="orders", autonomy_level="auto")
async def order_agent(intent: Intent, context: AgentContext) -> AgentResponse:
    return AgentResponse(result={"order_count": 42})
```

```bash
uvicorn myapp:app --reload
curl -X POST http://127.0.0.1:8000/agent/orders \
    -H 'content-type: application/json' \
    -d '{"intent": "How many orders do we have?"}'
```

Every app gets these for free:

| Path | Description |
|---|---|
| `POST /agent/{name}` | One per registered handler |
| `GET /health` | Health check with version, endpoints, ops-agent status |
| `GET /capabilities` | Structured metadata for every endpoint |
| `GET /openapi.json` | OpenAPI 3.1.0 schema |
| `GET /docs` | Swagger UI |
| `GET /redoc` | ReDoc UI |

### 2. With an LLM and a safety harness

Add an LLM backend and a `HarnessEngine` and the framework will generate
*and* safely execute Python code from natural language:

```python
from agenticapi import AgenticApp, CodePolicy, DataPolicy, HarnessEngine
from agenticapi.runtime.llm import AnthropicBackend

app = AgenticApp(
    title="Harnessed Agent",
    llm=AnthropicBackend(),  # reads ANTHROPIC_API_KEY from the environment
    harness=HarnessEngine(
        policies=[
            CodePolicy(denied_modules=["os", "subprocess"], deny_eval_exec=True),
            DataPolicy(readable_tables=["orders", "products"], deny_ddl=True),
        ],
    ),
)

@app.agent_endpoint(name="analytics", autonomy_level="supervised")
async def analytics(intent, context):
    pass  # The harness pipeline handles everything
```

The full request pipeline becomes:

```
parse intent
  -> generate code via LLM
  -> evaluate policies
  -> AST static analysis
  -> approval check (optional)
  -> sandboxed execution
  -> post-execution monitors and validators
  -> audit trace
  -> response
```

### 3. Multiple endpoints with routers

```python
from agenticapi import AgenticApp, IntentScope
from agenticapi.routing import AgentRouter

orders = AgentRouter(prefix="orders", tags=["orders"])
products = AgentRouter(prefix="products", tags=["products"])

@orders.agent_endpoint(
    name="query",
    intent_scope=IntentScope(allowed_intents=["order.*"]),
    autonomy_level="auto",
)
async def order_query(intent, context):
    return {"orders": [{"id": 1, "total": 150}], "count": 1}

@products.agent_endpoint(name="search", autonomy_level="auto")
async def product_search(intent, context):
    return {"products": [{"name": "Widget", "price": 29.99}]}

app = AgenticApp(title="Ecommerce Agent")
app.include_router(orders)
app.include_router(products)
```

### 4. Programmatic usage (no HTTP)

```python
response = await app.process_intent(
    "Show me last month's orders",
    endpoint_name="orders.query",
    session_id="session-123",
)

print(response.result)          # The handler's return value
print(response.generated_code)  # Code the LLM generated, if using harness
print(response.reasoning)       # The LLM's reasoning chain
```

---

## How it maps to FastAPI

If you know FastAPI, you already mostly know AgenticAPI:

| FastAPI | AgenticAPI | Notes |
|---|---|---|
| `FastAPI()` | `AgenticApp()` | Main ASGI app |
| `@app.get("/path")` | `@app.agent_endpoint(name=...)` | Endpoint registration |
| `APIRouter` | `AgentRouter` | Grouping with prefix and tags |
| `Request` | `Intent` | Input — natural language plus parsed action |
| `Response` | `AgentResponse` | Output with result, reasoning, trace ID |
| `HTMLResponse` | `HTMLResult` | HTML page response |
| `PlainTextResponse` | `PlainTextResult` | Plain text response |
| `FileResponse` | `FileResult` | File download |
| `BackgroundTasks` | `AgentTasks` | Post-response task execution |
| `app.add_middleware()` | `app.add_middleware()` | Same Starlette middleware |
| `UploadFile` | `UploadedFiles` | Multipart upload |
| `Security(...)` | `Authenticator` | API key, Bearer, Basic auth |
| `/docs` | `/docs` | Swagger UI (auto) |

You can mount existing FastAPI apps inside AgenticAPI, and you can expose
AgenticAPI endpoints as conventional REST routes — see
[REST and FastAPI compatibility](#rest-and-fastapi-compatibility).

---

## The harness: making LLM code safe

Every piece of LLM-generated code passes through a defence-in-depth
pipeline before it gets anywhere near your data:

```
generated code
  -> policy evaluation       (4 policy types, declarative)
  -> static AST analysis     (forbidden imports, eval/exec, getattr, file I/O)
  -> approval check          (human-in-the-loop for sensitive operations)
  -> process sandbox         (isolated subprocess, timeout, resource limits)
  -> monitors & validators   (post-execution checks)
  -> audit trail             (bounded ExecutionTrace)
```

### Policies

```python
from agenticapi import CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy

CodePolicy(
    denied_modules=["os", "subprocess"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
)
DataPolicy(
    readable_tables=["orders"],
    restricted_columns=["password_hash"],
    deny_ddl=True,
)
ResourcePolicy(
    max_cpu_seconds=30,
    max_memory_mb=512,
    max_execution_time_seconds=60,
)
RuntimePolicy(max_code_complexity=500, max_code_lines=500)
```

Policies are pure functions of the generated code (sync, no I/O, fully
deterministic), which makes them easy to test and easy to layer.

### Approval workflows

```python
from agenticapi import ApprovalRule, ApprovalWorkflow, HarnessEngine

harness = HarnessEngine(
    policies=[code_policy, data_policy],
    approval_workflow=ApprovalWorkflow(rules=[
        ApprovalRule(
            name="write_approval",
            require_for_actions=["write"],
            approvers=["admin"],
        ),
    ]),
)
```

When a request hits a matching rule, the endpoint returns **HTTP 202** with
a `request_id`. Resolve it later with
`await workflow.resolve(id, approved=True, approver="admin")`.

### Audit trail

Every harness execution produces an `ExecutionTrace` containing the intent,
the generated code, every policy decision, the result, the duration, and
any error. Traces are stored via an `AuditRecorder` (in-memory by default;
swap in your own implementation to ship to Prometheus, Elasticsearch, etc.).

---

## Authentication

```python
from agenticapi.security import APIKeyHeader, AuthCredentials, AuthUser, Authenticator

api_key = APIKeyHeader(name="X-API-Key")

async def verify(credentials: AuthCredentials) -> AuthUser | None:
    if credentials.credentials == "secret-key":
        return AuthUser(user_id="user-1", username="alice", roles=("admin",))
    return None

auth = Authenticator(scheme=api_key, verify=verify)

@app.agent_endpoint(name="orders", auth=auth)        # Per-endpoint
async def orders(intent, context):
    ...

# or app-wide:
app = AgenticApp(auth=auth)
```

Built-in schemes: `APIKeyHeader`, `APIKeyQuery`, `HTTPBearer`, `HTTPBasic`.
The authenticated user is available inside the handler as
`context.metadata["auth_user"]`.

---

## Custom responses and HTMX

Handlers default to JSON, but they can return any of these instead:

```python
from agenticapi import HTMLResult, PlainTextResult, FileResult

@app.agent_endpoint(name="dashboard")
async def dashboard(intent, context):
    return HTMLResult(content="<h1>Dashboard</h1><p>Welcome!</p>")

@app.agent_endpoint(name="status")
async def status(intent, context):
    return PlainTextResult(content="OK")

@app.agent_endpoint(name="export")
async def export(intent, context):
    return FileResult(
        content=b"name,value\nalice,42",
        media_type="text/csv",
        filename="export.csv",
    )
```

### HTMX integration

Build interactive web apps with partial-page updates:

```python
from agenticapi import HTMLResult, HtmxHeaders
from agenticapi.interface.htmx import htmx_response_headers

@app.agent_endpoint(name="items")
async def items(intent, context, htmx: HtmxHeaders):
    if htmx.is_htmx:
        return HTMLResult(content="<li>Item 1</li>")          # fragment
    return HTMLResult(content="<html><body>Full page</body></html>")  # full page

@app.agent_endpoint(name="add")
async def add(intent, context, htmx: HtmxHeaders):
    headers = htmx_response_headers(trigger="itemAdded", reswap="beforeend")
    return HTMLResult(content="<li>New item</li>", headers=headers)
```

`HtmxHeaders` is auto-injected when present in the handler signature, and
exposes `is_htmx`, `boosted`, `target`, `trigger`, `trigger_name`,
`current_url`, and `prompt`.

---

## File upload and download

```python
from agenticapi.interface.upload import UploadedFiles

@app.agent_endpoint(name="analyze")
async def analyze(intent, context, files: UploadedFiles):
    doc = files["document"]   # .filename, .content (bytes), .size, .content_type
    return {"filename": doc.filename, "size": doc.size}
```

```bash
curl -F 'intent=Analyze this' -F 'document=@report.pdf' \
    http://localhost:8000/agent/analyze
```

Limit: 50 MB per file. Handlers can also return Starlette `Response`,
`StreamingResponse`, or `FileResponse` directly for full control.

---

## LLM backends

| Backend | Provider | Default Model | Env Variable |
|---|---|---|---|
| `AnthropicBackend` | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `OpenAIBackend` | OpenAI | `gpt-5.4-mini` | `OPENAI_API_KEY` |
| `GeminiBackend` | Google | `gemini-2.5-flash` | `GOOGLE_API_KEY` |
| `MockBackend` | (testing) | `mock` | — |

```python
from agenticapi.runtime.llm import AnthropicBackend, GeminiBackend, OpenAIBackend

llm = AnthropicBackend(model="claude-sonnet-4-6", timeout=120.0)
```

All backends implement the `LLMBackend` protocol — `generate()`,
`generate_stream()`, and a `model_name` property — so you can drop in your
own implementation in two minutes if you need to.

---

## Tools

Tools are pluggable adapters for databases, caches, HTTP clients, queues,
and anything else generated code might need to call. They're collected in
a `ToolRegistry` and made available to the LLM during code generation.

```python
from agenticapi.runtime.tools import (
    CacheTool,
    DatabaseTool,
    HttpClientTool,
    QueueTool,
    ToolRegistry,
)

registry = ToolRegistry()
registry.register(DatabaseTool(name="db", execute_fn=my_query_fn, read_only=True))
registry.register(CacheTool(name="cache", default_ttl_seconds=300))
registry.register(HttpClientTool(name="api", allowed_hosts=["api.example.com"]))
registry.register(QueueTool(name="queue", max_size=1000))

app = AgenticApp(llm=llm, harness=harness, tools=registry)
```

Custom tools just need to satisfy the `Tool` protocol: a `definition`
property returning a `ToolDefinition`, and an `async def invoke(**kwargs)`
method.

---

## Background tasks

```python
from agenticapi import AgentTasks

@app.agent_endpoint(name="signup")
async def signup(intent, context, tasks: AgentTasks):
    tasks.add_task(send_welcome_email, user_id=123)
    tasks.add_task(update_analytics, action="signup")
    return {"status": "signed up"}
```

Sync and async callables are both supported. Failed tasks are logged but
don't block other tasks or the response.

---

## Sessions

```python
response = await app.process_intent(
    "Show me last month's orders",
    endpoint_name="orders.query",
    session_id="alice-session",  # opt into session tracking
)
```

Sessions accumulate conversation history with TTL expiration so multi-turn
flows can reference earlier turns. The session manager is exposed on the
app as `app.session_manager`.

---

## MCP support

Expose your endpoints as [Model Context Protocol](https://modelcontextprotocol.io)
tools — Claude Desktop, Cursor, and other MCP-aware clients can use them
directly.

```bash
pip install agenticapi[mcp]
```

```python
from agenticapi.interface.compat.mcp import expose_as_mcp

@app.agent_endpoint(name="search", enable_mcp=True)
async def search(intent, context):
    ...

app.add_routes(expose_as_mcp(app, path="/mcp"))
```

Test with `npx @modelcontextprotocol/inspector http://localhost:8000/mcp`.

---

## REST and FastAPI compatibility

Coexist with — or migrate from — existing FastAPI apps:

```python
from agenticapi.interface.compat import expose_as_rest, mount_fastapi

# Mount AgenticAPI inside an existing FastAPI app:
mount_fastapi(agenticapi_app, fastapi_app, path="/agent")

# Or expose AgentEndpoints as conventional REST routes:
app.add_routes(expose_as_rest(app, prefix="/rest"))
```

---

## Extensions

Large or fast-moving integrations live as **independently-installable
packages** under `extensions/`, with their own `pyproject.toml` and release
cadence. The first one wraps the Claude Agent SDK:

### `agenticapi-claude-agent-sdk`

Run the **full Claude Agent SDK loop** (planning, tool use, reflection,
structured output) inside an AgenticAPI endpoint, with AgenticAPI policies
bridged into Claude's permission system and AgenticAPI tools exposed via
an in-process MCP server.

```bash
pip install agenticapi-claude-agent-sdk
```

```python
from agenticapi import AgenticApp, CodePolicy
from agenticapi_claude_agent_sdk import ClaudeAgentRunner

runner = ClaudeAgentRunner(
    system_prompt="You are a coding assistant.",
    allowed_tools=["Read", "Glob", "Grep"],
    policies=[CodePolicy(denied_modules=["os", "subprocess"])],
)

app = AgenticApp(title="claude-sdk-demo")

@app.agent_endpoint(name="assistant", autonomy_level="manual")
async def assistant(intent, context):
    return await runner.run(intent=intent, context=context)
```

For a runnable end-to-end demo see
[`examples/13_claude_agent_sdk/`](./examples/13_claude_agent_sdk/), and
[`extensions/agenticapi-claude-agent-sdk/`](./extensions/agenticapi-claude-agent-sdk/)
for the full extension README, more examples, and design notes.

---

## Examples

Thirteen example apps, from minimal hello-world to a full Claude Agent
SDK loop:

| Example | LLM | What it demonstrates |
|---|---|---|
| [01_hello_agent](./examples/01_hello_agent) | None | Minimal single endpoint |
| [02_ecommerce](./examples/02_ecommerce) | None | Routers, policies, approval, tools |
| [03_openai_agent](./examples/03_openai_agent) | OpenAI | Full harness pipeline with GPT |
| [04_anthropic_agent](./examples/04_anthropic_agent) | Anthropic | Claude with `ResourcePolicy` |
| [05_gemini_agent](./examples/05_gemini_agent) | Gemini | Sessions and multi-turn conversations |
| [06_full_stack](./examples/06_full_stack) | Configurable | Pipeline, ops, middleware, tasks, files, REST |
| [07_comprehensive](./examples/07_comprehensive) | Configurable | Multi-feature DevOps platform per endpoint |
| [08_mcp_agent](./examples/08_mcp_agent) | None | MCP server with selective endpoint exposure |
| [09_auth_agent](./examples/09_auth_agent) | None | API key auth with role-based access |
| [10_file_handling](./examples/10_file_handling) | None | Upload, download, and streaming |
| [11_html_responses](./examples/11_html_responses) | None | HTML pages, plain text, custom response types |
| [12_htmx](./examples/12_htmx) | None | HTMX interactive todo app with partial updates |
| [13_claude_agent_sdk](./examples/13_claude_agent_sdk) | Anthropic (optional) | Full Claude Agent SDK loop via the extension, with policies, MCP-bridged tools, and an audit trail |

Run any example:

```bash
agenticapi dev --app examples.01_hello_agent.app:app
```

---

## Development

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
uv sync --group dev
```

### Testing

```bash
uv run pytest                            # all 740 tests
uv run pytest --ignore=tests/benchmarks  # skip benchmarks (faster)
uv run pytest tests/unit/ -xvs           # unit tests, verbose, fail-fast
uv run pytest tests/e2e/ -v              # e2e tests for all 13 examples
uv run pytest -m "not requires_llm"      # skip tests needing API keys
uv run pytest --cov=src/agenticapi       # coverage report (89%)
```

The independent extension under `extensions/agenticapi-claude-agent-sdk/`
has its own offline test suite (38 tests, no real Claude API calls
needed):

```bash
uv pip install -e extensions/agenticapi-claude-agent-sdk --no-deps
uv run --project . pytest extensions/agenticapi-claude-agent-sdk/tests
```

### Code quality

```bash
uv run ruff format src/ tests/           # format
uv run ruff check src/ tests/            # lint
uv run mypy src/agenticapi/              # type check (strict, py.typed)
```

A complete CI-equivalent run:

```bash
uv run ruff format --check src/ tests/ \
  && uv run ruff check src/ tests/ \
  && uv run mypy src/agenticapi/ \
  && uv run pytest --ignore=tests/benchmarks
```

### CLI

```bash
agenticapi dev --app myapp:app           # dev server with auto-reload
agenticapi console --app myapp:app       # interactive REPL
agenticapi version                       # show version
```

### Docs

```bash
mkdocs serve -a 127.0.0.1:8001            # live-reloading docs
mkdocs build                              # static site in site/
```

---

## Project layout

```
src/agenticapi/
    app.py                AgenticApp — main ASGI application
    security.py           Authentication (APIKeyHeader, HTTPBearer, Authenticator, …)
    routing.py            AgentRouter — endpoint grouping
    openapi.py            OpenAPI schema, Swagger UI, ReDoc
    types.py              AutonomyLevel, Severity, TraceLevel
    exceptions.py         Exception hierarchy with HTTP status mapping
    py.typed              Marker so mypy / pyright pick up our types

    interface/
        intent.py         Intent, IntentParser, IntentScope
        response.py       AgentResponse, FileResult, HTMLResult, PlainTextResult
        htmx.py           HtmxHeaders, htmx_response_headers
        upload.py         UploadFile, UploadedFiles
        tasks.py          AgentTasks (background tasks)
        session.py        SessionManager with TTL expiration
        compat/           REST, FastAPI, and MCP compatibility
        a2a/              Agent-to-Agent protocol, capability, trust

    harness/
        engine.py         HarnessEngine — safety pipeline orchestrator
        policy/           CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
        sandbox/          ProcessSandbox, AST analysis, monitors, validators
        approval/         ApprovalWorkflow, ApprovalRule
        audit/            AuditRecorder, ExecutionTrace, exporters

    runtime/
        code_generator.py LLM-powered code generation
        context.py        AgentContext, ContextWindow
        llm/              Backends: Anthropic, OpenAI, Gemini, Mock
        tools/            DatabaseTool, CacheTool, HttpClientTool, QueueTool
        prompts/          Prompt templates for code generation and intent parsing

    application/
        pipeline.py       DynamicPipeline, PipelineStage

    ops/
        base.py           OpsAgent, OpsHealthStatus

    testing/              mock_llm, MockSandbox, AgentTestCase, assertions, fixtures
    cli/                  Dev server, interactive console, version

examples/                 12 runnable example apps
extensions/
    agenticapi-claude-agent-sdk/   Claude Agent SDK integration
docs/                     Guides, API reference, architecture
development/              Contributor docs (architecture, modules, security, …)
```

**Stats**: 81 source files, ~10,600 lines of code, 740 tests, 89% coverage,
13 examples, 1 extension (38 extra offline tests).

---

## Requirements

- **Python** ≥ 3.13
- **[Starlette](https://www.starlette.io/)** ≥ 1.0
- **[Pydantic](https://docs.pydantic.dev/)** ≥ 2.12
- **[structlog](https://www.structlog.org/)** ≥ 25.0
- **[httpx](https://www.python-httpx.org/)** ≥ 0.28
- **[python-multipart](https://github.com/Kludex/python-multipart)** ≥ 0.0.20
- LLM SDKs:
  [anthropic](https://github.com/anthropics/anthropic-sdk-python) ≥ 0.89,
  [openai](https://github.com/openai/openai-python) ≥ 2.30,
  [google-genai](https://github.com/googleapis/python-genai) ≥ 1.70

Optional:
- [mcp](https://github.com/modelcontextprotocol/python-sdk) ≥ 1.27 — only
  needed if you use the MCP server compat layer

---

## Contributing

Bug reports, feature requests, and pull requests are welcome. See
[CONTRIBUTING.md](./CONTRIBUTING.md) and [SECURITY.md](./SECURITY.md) for
the details.

If you're adding code, please run the full quality suite first:

```bash
uv run ruff format --check src/ tests/ \
  && uv run ruff check src/ tests/ \
  && uv run mypy src/agenticapi/ \
  && uv run pytest --ignore=tests/benchmarks
```

---

## License

[MIT](./LICENSE) — © 2026 shibuiwilliam.
