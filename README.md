# AgenticAPI

**Agent-native web framework for Python** — build APIs where endpoints understand natural language, generate code on the fly, and execute it safely.

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![Tests](https://img.shields.io/badge/tests-681%20passed-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-89%25-brightgreen.svg)]()

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
    -H "Content-Type: application/json" \
    -d '{"intent": "Hello, how are you?"}'
```

Interactive API docs are auto-generated at `/docs` (Swagger UI) and `/redoc`.

---

## What is AgenticAPI?

AgenticAPI is like **FastAPI for AI agents**. Where FastAPI helps you build type-safe REST APIs, AgenticAPI helps you build **agent-powered APIs** with safety guardrails built in.

Your endpoints accept natural language intents instead of structured requests. Under the hood, an LLM can generate Python code to fulfill the intent, and a multi-layered harness system evaluates, sandboxes, and audits every execution before it touches your data.

You can use it with or without an LLM — at its simplest, it's just a decorator-based ASGI framework. At its most powerful, it's a complete agent execution platform.

---

## Features

| Category | What you get |
|---|---|
| **Agent endpoints** | Decorator-based registration, natural language intents, routers with prefix/tags |
| **Multi-LLM** | Anthropic Claude, OpenAI GPT, Google Gemini — swap with one line, or bring your own |
| **Safety harness** | Code policies, data policies, resource limits, static AST analysis, process sandbox |
| **Approval workflows** | Declarative rules for human-in-the-loop approval of sensitive operations |
| **Authentication** | API key, Bearer token, Basic auth — per-endpoint, per-router, or app-wide |
| **File handling** | Upload via multipart (50 MB limit), download via `FileResult`, streaming responses |
| **MCP support** | Expose endpoints as MCP tools for Claude Desktop, Cursor, and other LLM clients |
| **OpenAPI docs** | Auto-generated Swagger UI, ReDoc, and OpenAPI 3.1.0 schema |
| **Background tasks** | `AgentTasks` for post-response processing (like FastAPI's `BackgroundTasks`) |
| **Middleware** | Full Starlette middleware support (CORS, compression, timing, etc.) |
| **Dynamic pipelines** | Agent-level processing stages composed at runtime |
| **Agent-to-Agent** | Capability discovery, trust scoring, inter-agent communication foundation |
| **Ops agents** | Autonomous monitoring agents with severity-based autonomy gating |
| **REST compatibility** | Mount FastAPI apps inside AgenticAPI, or expose agent endpoints as REST routes |
| **Sessions** | Multi-turn conversation support with context accumulation and TTL |
| **Observability** | Structured logging via structlog, execution traces, bounded audit records |
| **ASGI-native** | Built on Starlette — runs with uvicorn, Daphne, Hypercorn |

---

## Installation

**Python 3.13+** required.

```bash
pip install agenticapi
```

Or for development:

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
uv sync --group dev
```

Optional extras:

```bash
pip install agenticapi[mcp]    # MCP server support
```

---

## Quick Start

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
uvicorn myapp:app --reload
curl -X POST http://127.0.0.1:8000/agent/orders \
    -H "Content-Type: application/json" \
    -d '{"intent": "How many orders do we have?"}'
```

Every app also gets `/health`, `/capabilities`, `/docs`, and `/redoc` for free.

### 2. With LLM and safety harness

Add an LLM backend and harness engine to generate and safely execute code from natural language:

```python
from agenticapi import AgenticApp, CodePolicy, DataPolicy, HarnessEngine
from agenticapi.runtime.llm import AnthropicBackend

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
    pass  # The harness pipeline handles everything
```

The pipeline: **parse intent -> generate code via LLM -> evaluate policies -> AST analysis -> process sandbox -> audit trace -> response**.

### 3. Multi-endpoint app with routers

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
print(response.generated_code)  # The code the LLM generated (if using harness)
print(response.reasoning)       # The LLM's reasoning
```

---

## How It Maps to FastAPI

If you know FastAPI, you already know the patterns:

| FastAPI | AgenticAPI | Notes |
|---|---|---|
| `FastAPI()` | `AgenticApp()` | Main app, ASGI-compatible |
| `@app.get("/path")` | `@app.agent_endpoint(name=...)` | Endpoint registration |
| `APIRouter` | `AgentRouter` | Grouping with prefix and tags |
| `Request` | `Intent` | Input (natural language) |
| `Response` | `AgentResponse` | Output with result, reasoning, trace |
| `BackgroundTasks` | `AgentTasks` | Post-response task execution |
| `Depends()` | `HarnessDepends()` | Dependency injection |
| `app.add_middleware()` | `app.add_middleware()` | Starlette middleware (CORS, etc.) |
| `UploadFile` | `UploadedFiles` | File upload via multipart |
| `FileResponse` | `FileResult` | File download |
| Security schemes | `Authenticator` | API key, Bearer, Basic auth |
| `/docs` | `/docs` | Swagger UI (auto-generated) |

---

## Safety: The Harness System

Every piece of LLM-generated code passes through a multi-layered safety pipeline:

```
Generated Code
  -> Policy Evaluation (4 policy types)
  -> Static AST Analysis (forbidden imports, eval/exec, file I/O, getattr)
  -> Approval Check (human-in-the-loop for sensitive operations)
  -> Process Sandbox (isolated subprocess with timeout + resource limits)
  -> Post-Execution Monitors + Validators
  -> Audit Trail Recording
```

### Policies

```python
from agenticapi import CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy

CodePolicy(
    denied_modules=["os", "subprocess", "sys"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
    max_code_lines=500,
)

DataPolicy(
    readable_tables=["orders", "products"],
    writable_tables=["orders"],
    restricted_columns=["password_hash", "ssn"],
    deny_ddl=True,
)

ResourcePolicy(max_cpu_seconds=30, max_memory_mb=512, max_execution_time_seconds=60)

RuntimePolicy(max_code_complexity=500, max_code_lines=500)
```

### Approval Workflows

```python
from agenticapi import ApprovalRule, ApprovalWorkflow, HarnessEngine

harness = HarnessEngine(
    policies=[code_policy, data_policy],
    approval_workflow=ApprovalWorkflow(rules=[
        ApprovalRule(
            name="write_approval",
            require_for_actions=["write", "execute"],
            approvers=["db_admin"],
            timeout_seconds=1800,
        ),
    ]),
)
```

When approval is required, the endpoint returns HTTP 202 with a `request_id`. Resolve it programmatically:

```python
await workflow.resolve(request_id, approved=True, approver="admin@example.com")
```

### Sandbox & Audit

Code runs in an isolated subprocess with timeout enforcement. User code is base64-encoded for safe transport. Every execution is recorded as an `ExecutionTrace` with the original intent, generated code, policy evaluations, and timing. The `AuditRecorder` has bounded storage (configurable `max_traces`) to prevent memory exhaustion.

---

## Authentication

Following FastAPI's security patterns:

```python
from agenticapi.security import APIKeyHeader, Authenticator, AuthUser, AuthCredentials

api_key = APIKeyHeader(name="X-API-Key")

async def verify(credentials: AuthCredentials) -> AuthUser | None:
    if credentials.credentials == "secret-key":
        return AuthUser(user_id="user-1", username="alice", roles=("admin",))
    return None

auth = Authenticator(scheme=api_key, verify=verify)

@app.agent_endpoint(name="orders", auth=auth)  # Per-endpoint
async def orders(intent, context):
    print(context.user_id)  # "user-1"

# Or app-wide:
app = AgenticApp(auth=auth)
```

Available schemes: `APIKeyHeader`, `APIKeyQuery`, `HTTPBearer`, `HTTPBasic`.

---

## File Upload & Download

```python
from agenticapi.interface.upload import UploadedFiles
from agenticapi.interface.response import FileResult

# Upload: add UploadedFiles parameter
@app.agent_endpoint(name="analyze")
async def analyze(intent, context, files: UploadedFiles):
    doc = files["document"]  # .filename, .content (bytes), .size, .content_type
    return {"filename": doc.filename, "size": doc.size}

# Download: return FileResult
@app.agent_endpoint(name="export")
async def export(intent, context):
    return FileResult(content=b"name,value\nalice,42", media_type="text/csv", filename="export.csv")
```

```bash
# Upload
curl -F 'intent=Analyze this' -F 'document=@report.pdf' http://localhost:8000/agent/analyze

# Download
curl -X POST http://localhost:8000/agent/export \
    -H "Content-Type: application/json" \
    -d '{"intent": "Export data"}' -o export.csv
```

Upload limit: 50 MB per file. Handlers can also return Starlette `Response`, `FileResponse`, or `StreamingResponse` directly.

---

## Middleware

Full Starlette middleware support, just like FastAPI:

```python
from starlette.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Or via constructor: `AgenticApp(middleware=[Middleware(CORSMiddleware, ...)])`.

Middleware wraps the entire ASGI app (all routes). For agent-specific request context enrichment inside handlers, use `DynamicPipeline` instead.

---

## MCP Support

Expose agent endpoints as [MCP](https://modelcontextprotocol.io) tools for Claude Desktop, Cursor, and other LLM clients:

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

```bash
npx @modelcontextprotocol/inspector http://127.0.0.1:8000/mcp
```

Only endpoints marked with `enable_mcp=True` are exposed as MCP tools.

---

## LLM Backends

| Backend | Provider | Default Model | Env Variable |
|---|---|---|---|
| `AnthropicBackend` | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `OpenAIBackend` | OpenAI | `gpt-5.4-mini` | `OPENAI_API_KEY` |
| `GeminiBackend` | Google | `gemini-2.5-flash` | `GOOGLE_API_KEY` |
| `MockBackend` | (Testing) | `mock` | -- |

All backends implement the `LLMBackend` protocol with configurable `timeout` (default 120s). Bring your own by implementing `generate()`, `generate_stream()`, and `model_name`.

---

## Background Tasks

Schedule work that runs after the response, just like FastAPI's `BackgroundTasks`:

```python
from agenticapi import AgentTasks

@app.agent_endpoint(name="signup")
async def signup(intent, context, tasks: AgentTasks):
    tasks.add_task(send_welcome_email, user_id=123)
    tasks.add_task(update_analytics, action="signup")
    return {"status": "signed up"}
    # send_welcome_email and update_analytics run after the response
```

Both sync and async callables are supported. Failed tasks are logged but don't block other tasks.

---

## Tools

Four built-in tools for generated code to interact with external systems:

```python
from agenticapi.runtime.tools import ToolRegistry, DatabaseTool, CacheTool, HttpClientTool, QueueTool

registry = ToolRegistry()
registry.register(DatabaseTool(name="db", execute_fn=my_query_fn, read_only=True))
registry.register(CacheTool(name="cache", default_ttl_seconds=300))
registry.register(HttpClientTool(name="api", allowed_hosts=["api.example.com"]))
registry.register(QueueTool(name="queue", max_size=1000))
```

Custom tools implement the `Tool` protocol -- provide a `definition` property and an `async invoke()` method.

---

## Dynamic Pipelines

Middleware-like processing stages that agents can compose at runtime:

```python
from agenticapi.application import DynamicPipeline, PipelineStage

pipeline = DynamicPipeline(
    base_stages=[
        PipelineStage("auth", handler=auth_fn, required=True, order=10),
        PipelineStage("rate_limit", handler=rate_fn, required=True, order=20),
    ],
    available_stages=[
        PipelineStage("cache", handler=cache_fn, order=30),
        PipelineStage("fraud_check", handler=fraud_fn, order=40),
    ],
)

result = await pipeline.execute(context={"user": "alice"}, selected_stages=["fraud_check"])
```

---

## REST Compatibility

```python
from agenticapi.interface.compat import mount_fastapi, mount_in_agenticapi, expose_as_rest

# Mount AgenticAPI inside FastAPI
mount_fastapi(agenticapi_app, fastapi_app, path="/agent")

# Mount FastAPI inside AgenticAPI
mount_in_agenticapi(agenticapi_app, fastapi_app, path="/api")

# Expose agent endpoints as REST GET/POST routes
app.add_routes(expose_as_rest(app, prefix="/rest"))
```

---

## Examples

Ten example apps, from minimal hello-world to a comprehensive full-stack warehouse system:

| Example | LLM | What it demonstrates |
|---|---|---|
| [01_hello_agent](./examples/01_hello_agent) | None | Minimal single endpoint |
| [02_ecommerce](./examples/02_ecommerce) | None | Routers, policies, approval, tools |
| [03_openai_agent](./examples/03_openai_agent) | OpenAI | Full harness pipeline with GPT |
| [04_anthropic_agent](./examples/04_anthropic_agent) | Anthropic | Claude with ResourcePolicy |
| [05_gemini_agent](./examples/05_gemini_agent) | Gemini | Sessions and multi-turn conversations |
| [06_full_stack](./examples/06_full_stack) | Configurable | Pipeline, ops, middleware, background tasks, file handling, REST compat |
| [07_comprehensive](./examples/07_comprehensive) | Configurable | Multi-feature per-endpoint DevOps platform |
| [08_mcp_agent](./examples/08_mcp_agent) | None | MCP server with selective endpoint exposure |
| [09_auth_agent](./examples/09_auth_agent) | None | API key auth with role-based access |
| [10_file_handling](./examples/10_file_handling) | None | Upload, download, and streaming |

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
uv run pytest                            # All 681 tests
uv run pytest tests/unit/ -xvs           # Unit tests, verbose
uv run pytest tests/e2e/ -v              # E2E tests for all 10 examples
uv run pytest -m "not requires_llm"      # Skip tests needing API keys
uv run pytest --cov=src/agenticapi       # Coverage report (89%)
```

### Code Quality

```bash
uv run ruff format src/ tests/           # Format
uv run ruff check src/ tests/            # Lint
uv run mypy src/agenticapi/              # Type check (strict)
```

### CLI

```bash
agenticapi dev --app myapp:app           # Dev server with auto-reload
agenticapi console --app myapp:app       # Interactive REPL
agenticapi version                       # Show version
```

---

## Project Structure

```
src/agenticapi/
    app.py                  AgenticApp -- main ASGI application
    security.py             Authentication (APIKeyHeader, HTTPBearer, Authenticator)
    routing.py              AgentRouter -- endpoint grouping
    openapi.py              OpenAPI schema, Swagger UI, ReDoc
    types.py                AutonomyLevel, Severity, TraceLevel
    exceptions.py           Exception hierarchy with HTTP status mapping
    interface/
        intent.py           Intent, IntentParser, IntentScope
        response.py         AgentResponse, FileResult, ResponseFormatter
        upload.py           UploadFile, UploadedFiles
        tasks.py            AgentTasks (background tasks)
        session.py          SessionManager with TTL expiration
        compat/             REST, FastAPI, and MCP compatibility
        a2a/                Agent-to-Agent protocol, capability, trust
    harness/
        engine.py           HarnessEngine -- safety pipeline orchestrator
        policy/             CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
        sandbox/            ProcessSandbox, static AST analysis, monitors, validators
        approval/           ApprovalWorkflow, ApprovalRule
        audit/              AuditRecorder, ExecutionTrace, exporters
    runtime/
        code_generator.py   LLM-powered code generation
        context.py          AgentContext, ContextWindow
        llm/                Backends: Anthropic, OpenAI, Gemini, Mock
        tools/              DatabaseTool, CacheTool, HttpClientTool, QueueTool
        prompts/            Prompt templates for code generation and intent parsing
    application/
        pipeline.py         DynamicPipeline, PipelineStage
    ops/
        base.py             OpsAgent, OpsHealthStatus
    testing/                mock_llm, MockSandbox, AgentTestCase, assertions, fixtures
    cli/                    Dev server, interactive console, version
examples/
    01_hello_agent/ .. 10_file_handling/   # 10 runnable example apps
docs/                       # Guides, API reference, architecture docs
```

---

## Requirements

- **Python** >= 3.13
- **[Starlette](https://www.starlette.io/)** >= 1.0
- **[Pydantic](https://docs.pydantic.dev/)** >= 2.12
- **[structlog](https://www.structlog.org/)** >= 25.0
- **[httpx](https://www.python-httpx.org/)** >= 0.28
- **[python-multipart](https://github.com/Kludex/python-multipart)** >= 0.0.20
- LLM SDKs: [anthropic](https://github.com/anthropics/anthropic-sdk-python) >= 0.89, [openai](https://github.com/openai/openai-python) >= 2.30, [google-genai](https://github.com/googleapis/python-genai) >= 1.70

## License

[MIT](./LICENSE)
