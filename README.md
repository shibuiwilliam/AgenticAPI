# AgenticAPI

**Agent-native web framework with harness engineering for Python.**

AgenticAPI lets you build web applications where endpoints accept natural language intents, dynamically generate code via LLMs, and execute it in a sandboxed, policy-controlled environment. Think of it as FastAPI for agent-powered APIs — with safety guardrails built in.

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
uvicorn examples.01_hello_agent.app:app --reload
```

```bash
# Send an intent
curl -X POST http://127.0.0.1:8000/agent/greeter \
    -H "Content-Type: application/json" \
    -d '{"intent": "Hello, how are you?"}'

# Interactive API docs (auto-generated)
open http://127.0.0.1:8000/docs
```

## Key Features

- **Intent-based endpoints** — Accept natural language instead of structured REST/GraphQL requests. The `IntentParser` converts raw text into typed `Intent` objects with action, domain, parameters, and confidence score.
- **Dynamic code generation** — LLM backends generate Python code on the fly based on user intent, available tools, and execution context.
- **Harness engineering** — A layered safety system that evaluates generated code against policies, runs static AST analysis, executes in a process sandbox, and records full audit traces — all before a single line of generated code touches your data.
- **Multi-LLM support** — Pluggable backends for Anthropic Claude, OpenAI GPT, and Google Gemini. Swap providers with a single config change, or bring your own via the `LLMBackend` protocol.
- **OpenAPI and Swagger UI** — Auto-generated OpenAPI 3.1.0 schema at `/openapi.json`, Swagger UI at `/docs`, and ReDoc at `/redoc` — just like FastAPI.
- **Approval workflows** — Declarative rules that require human approval for sensitive operations, with configurable approvers, timeouts, and notification channels.
- **Built-in tools** — Database, cache, HTTP client, and queue tools that agents can use in generated code, each with its own access controls.
- **Dynamic pipelines** — Middleware-like processing stages that agents can compose at runtime based on request content.
- **Agent-to-Agent protocol** — Foundation for inter-agent communication with capability discovery, negotiation, and trust scoring.
- **Ops agents** — Register autonomous operational agents for monitoring, healing, and performance tuning, with severity-based autonomy gating.
- **ASGI-native** — Built on Starlette. Runs on uvicorn, Daphne, Hypercorn, or any ASGI server. Follows patterns familiar to FastAPI developers.
- **Session management** — Multi-turn conversation support with context accumulation and TTL-based expiration.
- **Full observability** — Structured logging via structlog, execution traces, audit records, and console/OpenTelemetry exporters for every agent operation.
- **REST compatibility** — Mount existing FastAPI apps inside AgenticAPI, or expose agent endpoints as conventional REST routes.
- **Capability discovery** — Built-in `GET /capabilities` endpoint exposes structured metadata about all registered endpoints for external agent integration.

## Architecture

Every request flows through a layered pipeline:

```
HTTP Request (ASGI)
  -> Interface Layer    Intent parsing, session management, response formatting
  -> Harness Engine     Policy evaluation, static analysis, approval workflows
  -> Agent Runtime      LLM code generation, context assembly, tool registry
  -> Sandbox            Isolated process execution with resource limits
  -> Response           Structured result with generated code, reasoning, trace ID
```

### How It Maps to FastAPI

If you know FastAPI, you already know the patterns:

| FastAPI | AgenticAPI | Notes |
|---|---|---|
| `FastAPI()` | `AgenticApp()` | Main app class, ASGI-compatible |
| `@app.get("/path")` | `@app.agent_endpoint(name=...)` | Endpoint registration decorator |
| `APIRouter` | `AgentRouter` | Endpoint grouping with prefix and tags |
| `Request` | `Intent` | Input abstraction (natural language) |
| `Response` | `AgentResponse` | Output with result, reasoning, trace |
| `Depends()` | `HarnessDepends()` | Dependency injection |
| Middleware | `DynamicPipeline` | Dynamic middleware composition |
| `/docs` | `/docs` | Swagger UI (auto-generated) |
| `/redoc` | `/redoc` | ReDoc UI (auto-generated) |
| `/openapi.json` | `/openapi.json` | OpenAPI 3.1.0 schema |

## Installation

Requires **Python 3.13+**.

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
pip install -e ".[dev]"
```

## Quick Start

### 1. Simple handler (no LLM)

The simplest mode — your handler receives a parsed intent and returns a response directly:

```python
from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="My Service")

@app.agent_endpoint(name="orders", autonomy_level="supervised")
async def order_agent(intent: Intent, context: AgentContext) -> AgentResponse:
    return AgentResponse(result={"order_count": 42})
```

Run it:

```bash
uvicorn myapp:app --reload
```

Test it:

```bash
curl -X POST http://127.0.0.1:8000/agent/orders \
    -H "Content-Type: application/json" \
    -d '{"intent": "How many orders do we have?"}'
```

Browse the auto-generated docs at `http://127.0.0.1:8000/docs`.

### 2. With LLM code generation and harness

When you provide an LLM backend and harness engine, AgenticAPI generates code dynamically and executes it safely:

```python
from agenticapi import AgenticApp, CodePolicy, HarnessEngine
from agenticapi.runtime.llm import AnthropicBackend

app = AgenticApp(
    title="Harnessed Agent",
    description="Agent API with safety guardrails",
    llm=AnthropicBackend(model="claude-sonnet-4-6"),
    harness=HarnessEngine(),
)

@app.agent_endpoint(
    name="analytics",
    autonomy_level="supervised",
    policies=[CodePolicy(denied_modules=["os", "subprocess", "sys"])],
)
async def analytics_agent(intent, context):
    pass  # The harness pipeline handles execution
```

The full pipeline: parse intent -> generate code via LLM -> evaluate against policies -> AST static analysis -> execute in sandbox -> record audit trace -> return response.

### 3. Using different LLM backends

```python
from agenticapi.runtime.llm import AnthropicBackend, OpenAIBackend, GeminiBackend

# Anthropic Claude
llm = AnthropicBackend(model="claude-sonnet-4-6")  # uses ANTHROPIC_API_KEY

# OpenAI GPT
llm = OpenAIBackend(model="gpt-5.4-mini")  # uses OPENAI_API_KEY

# Google Gemini
llm = GeminiBackend(model="gemini-2.5-flash")  # uses GOOGLE_API_KEY
```

All backends implement the same `LLMBackend` protocol with `generate()` and `generate_stream()` methods.

### 4. Multi-endpoint app with routers

```python
from agenticapi import AgenticApp, IntentScope
from agenticapi.routing import AgentRouter

orders_router = AgentRouter(prefix="orders", tags=["orders"])
products_router = AgentRouter(prefix="products", tags=["products"])

@orders_router.agent_endpoint(
    name="query",
    description="Query order information",
    intent_scope=IntentScope(allowed_intents=["order.*"]),
    autonomy_level="auto",
)
async def order_query(intent, context):
    return {"orders": [...], "total_count": 42}

@products_router.agent_endpoint(name="search", autonomy_level="auto")
async def product_search(intent, context):
    return {"products": [...]}

app = AgenticApp(title="Ecommerce Agent")
app.include_router(orders_router)
app.include_router(products_router)
```

### 5. Programmatic usage

You can call the agent pipeline directly without HTTP:

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

## OpenAPI and Interactive Docs

Every AgenticAPI app automatically serves OpenAPI documentation — no configuration needed:

| Route | What it serves |
|---|---|
| `GET /openapi.json` | OpenAPI 3.1.0 JSON schema |
| `GET /docs` | Swagger UI (interactive) |
| `GET /redoc` | ReDoc UI |

The schema includes every registered agent endpoint as a `POST /agent/{name}` operation, with request/response schemas, intent scope metadata, policy names, and autonomy levels.

```python
# Customize or disable docs
app = AgenticApp(
    title="My API",
    version="2.0.0",
    description="My agent-powered service",
    docs_url="/api/docs",          # Custom Swagger UI path
    redoc_url="/api/redoc",        # Custom ReDoc path
    openapi_url="/api/schema.json", # Custom schema path
)

# Disable docs entirely
app = AgenticApp(openapi_url=None)
```

## Safety: The Harness System

AgenticAPI's harness system provides multi-layered defense for agent-generated code. Every piece of code an LLM generates passes through this pipeline before execution.

### Policy Evaluation

Four built-in policy types control what generated code is allowed to do:

```python
from agenticapi import CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy

# Code safety — control imports, builtins, and patterns
code_policy = CodePolicy(
    denied_modules=["os", "subprocess", "sys", "shutil"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
    allow_network=False,
    max_code_lines=500,
)

# Data access — control which tables and columns agents can touch
data_policy = DataPolicy(
    readable_tables=["orders", "products"],
    writable_tables=["orders", "cart"],
    restricted_columns=["password_hash", "ssn", "credit_card"],
    deny_ddl=True,
    max_result_rows=1000,
)

# Resource limits — prevent runaway code
resource_policy = ResourcePolicy(
    max_cpu_seconds=30,
    max_memory_mb=512,
    max_execution_time_seconds=60,
)

# Complexity limits — reject overly complex code
runtime_policy = RuntimePolicy(
    max_code_complexity=50,  # AST node count
    max_code_lines=500,
)
```

### Static Analysis

Before execution, generated code is parsed into an AST and checked for:
- Forbidden module imports (configurable allow/deny lists)
- `eval()` / `exec()` usage
- `__import__()` calls
- Dangerous builtins (`compile`, `globals`, `locals`, `vars`, `getattr`, `setattr`, `delattr`)
- File I/O operations (`open()`)
- Syntax errors

### Approval Workflows

Sensitive operations can require human approval before execution:

```python
from agenticapi import ApprovalRule, ApprovalWorkflow, HarnessEngine

workflow = ApprovalWorkflow(
    rules=[
        ApprovalRule(
            name="write_approval",
            require_for_actions=["write", "execute"],
            require_for_domains=["order"],
            approvers=["db_admin"],
            timeout_seconds=1800,
        ),
    ]
)

harness = HarnessEngine(
    policies=[code_policy, data_policy],
    approval_workflow=workflow,
)
```

When an approval is required, the harness raises `ApprovalRequired` with a request ID. The request can then be resolved externally:

```python
await workflow.resolve(request_id, approved=True, approver="admin@example.com")
```

### Process Sandbox

Code runs in an isolated subprocess with:
- Execution timeout enforcement
- stdout/stderr capture
- Resource metrics collection (CPU time, memory, wall-clock time)
- Post-execution monitors (`ResourceMonitor`, `OutputSizeMonitor`)
- Post-execution validators (`OutputTypeValidator`, `ReadOnlyValidator`)

### Audit Trail

Every execution is recorded as an `ExecutionTrace` containing:
- Original intent and parsed action
- Generated code and LLM reasoning
- Policy evaluation results
- Execution output and duration
- Any errors or approval requests

```python
# Retrieve audit records
records = harness.audit_recorder.get_records(endpoint_name="orders", limit=50)
for trace in records:
    print(f"[{trace.timestamp}] {trace.intent_raw} -> {trace.execution_duration_ms}ms")
```

## Intent System

The `IntentParser` converts natural language into structured `Intent` objects:

```python
from agenticapi.interface.intent import IntentParser, IntentAction

parser = IntentParser()  # keyword-based (no LLM needed)
intent = await parser.parse("Show me the top 10 orders by revenue")

intent.action      # IntentAction.READ
intent.domain      # "order"
intent.parameters  # {}
intent.confidence  # 0.6
intent.raw         # "Show me the top 10 orders by revenue"
```

When an LLM backend is provided, the parser uses it for higher accuracy:

```python
parser = IntentParser(llm=AnthropicBackend())
intent = await parser.parse("Cancel order #1234 and refund the customer")
# action=WRITE, domain="order", parameters={"order_id": "1234"}, confidence=0.95
```

**Available actions:** `READ`, `WRITE`, `ANALYZE`, `EXECUTE`, `CLARIFY`

**Intent scoping** constrains which intents an endpoint accepts:

```python
from agenticapi import IntentScope

@app.agent_endpoint(
    name="orders",
    intent_scope=IntentScope(
        allowed_intents=["order.*"],         # Allow all order intents
        denied_intents=["order.bulk_delete"], # But not bulk deletes
    ),
)
async def order_agent(intent, context):
    ...
```

## Tools

Agents use tools to interact with external systems. Four built-in tools are provided:

```python
from agenticapi.runtime.tools import ToolRegistry, DatabaseTool, CacheTool, HttpClientTool, QueueTool

# Database — wraps an async query function
db = DatabaseTool(
    name="main_db",
    execute_fn=my_async_db_execute,
    read_only=True,  # Blocks INSERT/UPDATE/DELETE/DROP
)

# Cache — in-memory key-value store with TTL
cache = CacheTool(name="app_cache", default_ttl_seconds=300, max_size=1000)

# HTTP client — makes external API calls with host allowlisting
http = HttpClientTool(
    name="api_client",
    allowed_hosts=["api.internal.example.com"],
    timeout=30.0,
)

# Queue — async message queue
queue = QueueTool(name="task_queue", max_size=1000)

# Register all tools
registry = ToolRegistry()
registry.register(db)
registry.register(cache)
registry.register(http)
registry.register(queue)
```

You can implement custom tools using the `Tool` protocol:

```python
from agenticapi.runtime.tools.base import Tool, ToolDefinition, ToolCapability

class MyTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="my_tool",
            description="Does something useful",
            capabilities=[ToolCapability.READ],
        )

    async def invoke(self, **kwargs) -> Any:
        ...
```

## LLM Backends

AgenticAPI ships with four LLM backend implementations:

| Backend | Provider | Default Model | Env Variable |
|---|---|---|---|
| `AnthropicBackend` | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `OpenAIBackend` | OpenAI | `gpt-5.4-mini` | `OPENAI_API_KEY` |
| `GeminiBackend` | Google | `gemini-2.5-flash` | `GOOGLE_API_KEY` |
| `MockBackend` | (Testing) | `mock` | — |

All backends are async-first and support both complete and streaming generation:

```python
from agenticapi.runtime.llm import OpenAIBackend
from agenticapi.runtime.llm.base import LLMPrompt, LLMMessage

backend = OpenAIBackend(model="gpt-5.4-mini")

# Complete generation
response = await backend.generate(LLMPrompt(
    system="You are a helpful assistant.",
    messages=[LLMMessage(role="user", content="Write a SQL query")],
))
print(response.content)
print(response.usage)  # LLMUsage(input_tokens=..., output_tokens=...)

# Streaming
async for chunk in backend.generate_stream(prompt):
    print(chunk.content, end="")
```

Implement your own backend — any class matching the `LLMBackend` protocol works without inheriting from AgenticAPI:

```python
class MyCustomBackend:
    async def generate(self, prompt: LLMPrompt) -> LLMResponse: ...
    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]: ...
    @property
    def model_name(self) -> str: ...
```

## Dynamic Pipelines

Compose middleware-like processing stages at runtime:

```python
from agenticapi.application import DynamicPipeline, PipelineStage

pipeline = DynamicPipeline(
    base_stages=[
        PipelineStage("auth", handler=auth_handler, required=True, order=10),
        PipelineStage("rate_limit", handler=rate_limiter, required=True, order=20),
    ],
    available_stages=[
        PipelineStage("cache", description="Cache lookup for read queries", handler=cache_handler),
        PipelineStage("fraud_check", description="Fraud detection for high-value orders", handler=fraud_checker),
    ],
    max_stages=10,
)

# Agents select stages dynamically based on request content
result = await pipeline.execute(
    context={"user": "alice", "amount": 50000},
    selected_stages=["fraud_check"],
)
# result.stages_executed: ["auth", "rate_limit", "fraud_check"]
# result.stage_timings_ms: {"auth": 1.2, "rate_limit": 0.3, "fraud_check": 5.1}
```

## Agent-to-Agent Communication

Foundation types for inter-agent communication:

```python
from agenticapi.interface.a2a import (
    Capability, CapabilityRegistry,
    A2AMessage, A2AMessageType, A2ARequest, A2AResponse,
    TrustPolicy, TrustScorer,
)

# Register capabilities
registry = CapabilityRegistry()
registry.register(Capability(
    name="inventory_lookup",
    description="Look up current inventory levels",
    sla_max_latency_ms=500,
    sla_availability=0.999,
))

# Trust scoring between agents
scorer = TrustScorer(policy=TrustPolicy(
    initial_trust=0.5,
    min_trust_for_read=0.3,
    min_trust_for_write=0.8,
))
scorer.record_success("agent-123")  # Trust increases
scorer.can_read("agent-123")        # True
scorer.can_write("agent-123")       # Depends on accumulated trust
```

Every app also exposes `GET /capabilities` for external agent discovery, returning structured metadata about all registered endpoints.

## Ops Agents

Register operational agents for autonomous system management:

```python
from agenticapi.ops import OpsAgent, OpsHealthStatus
from agenticapi.types import AutonomyLevel, Severity

class LogAnalyst(OpsAgent):
    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def check_health(self) -> OpsHealthStatus:
        return OpsHealthStatus(healthy=self._running)

agent = LogAnalyst(
    name="log-analyst",
    autonomy=AutonomyLevel.SUPERVISED,
    max_severity=Severity.MEDIUM,
)
app.register_ops_agent(agent)

# Severity-based autonomy gating
agent.can_handle_autonomously(Severity.LOW)       # True
agent.can_handle_autonomously(Severity.CRITICAL)   # False — needs human
```

Ops agents participate in the app lifecycle (started on startup, stopped on shutdown) and their health is reported in the `GET /health` response.

## REST Compatibility

Mount existing FastAPI apps or expose agent endpoints as REST:

```python
from agenticapi.interface.compat import mount_fastapi, mount_in_agenticapi, expose_as_rest

# Mount AgenticAPI inside an existing FastAPI app
from fastapi import FastAPI
fastapi_app = FastAPI()
mount_fastapi(agenticapi_app, fastapi_app, path="/agent")

# Or mount FastAPI inside AgenticAPI
mount_in_agenticapi(agenticapi_app, fastapi_app, path="/api/v1")

# Expose agent endpoints as REST routes
rest_routes = expose_as_rest(agenticapi_app, endpoint_name="orders")
```

## Testing

AgenticAPI includes a testing framework for writing deterministic agent tests:

```python
from agenticapi.testing import mock_llm, MockSandbox, create_test_app
from agenticapi.testing.assertions import assert_code_safe, assert_policy_enforced

# Mock LLM responses
with mock_llm(responses=["SELECT COUNT(*) FROM orders"]) as backend:
    response = await backend.generate(prompt)
    assert response.content == "SELECT COUNT(*) FROM orders"

# Mock sandbox
sandbox = MockSandbox(
    allowed_results={"SELECT COUNT(*)": [{"count": 42}]},
    denied_operations=["DROP TABLE"],
)

# Create a fully wired test app
app = create_test_app(
    policies=[CodePolicy(denied_modules=["os"])],
    llm_responses=["SELECT 1"],
)

# Safety assertions
assert_code_safe("x = 1 + 2")  # Passes
assert_code_safe("import os")  # Raises AssertionError
```

## Examples

Seven example apps are included, from a minimal hello-world to a full-stack multi-feature composition. See the [examples README](./examples/README.md) for details, curl commands, and per-endpoint documentation.

## Development

### Setup

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Running Tests

```bash
# All tests (564 tests)
make test

# With coverage (88%+)
make test-cov

# Specific module
pytest tests/unit/runtime/test_llm_backend.py -xvs

# Skip tests that require LLM API keys
pytest -m "not requires_llm"

# Benchmarks
make test-benchmark
```

### Code Quality

```bash
# Format + lint + typecheck in one command
make check

# Auto-fix formatting and lint issues
make fix

# Or individually
make format      # ruff format
make lint        # ruff check
make typecheck   # mypy
```

### Dev Server

```bash
make dev              # Hello agent example
make dev-ecommerce    # Ecommerce example
make dev-openai       # OpenAI example (requires OPENAI_API_KEY)
```

### Full CI Pipeline

```bash
make ci       # lint + typecheck + test
make ci-cov   # lint + typecheck + test with coverage
```

## Project Structure

```
src/agenticapi/
    app.py                  # AgenticApp — main ASGI application
    openapi.py              # OpenAPI schema generation, Swagger UI, ReDoc
    routing.py              # AgentRouter — endpoint grouping
    types.py                # Shared types (AutonomyLevel, Severity, TraceLevel)
    exceptions.py           # Exception hierarchy with HTTP status mapping
    params.py               # HarnessDepends — dependency injection
    interface/
        intent.py           # Intent, IntentParser, IntentScope, IntentAction
        session.py          # SessionManager with TTL-based expiration
        response.py         # AgentResponse, ResponseFormatter
        endpoint.py         # AgentEndpointDef
        compat/             # REST and FastAPI compatibility layer
        a2a/                # Agent-to-Agent protocol, capability, trust
    harness/
        engine.py           # HarnessEngine — orchestrates the safety pipeline
        policy/             # CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
        sandbox/            # ProcessSandbox, static AST analysis, monitors, validators
        approval/           # ApprovalWorkflow, ApprovalRule, notifiers
        audit/              # AuditRecorder, ExecutionTrace, exporters
    runtime/
        code_generator.py   # LLM-powered code generation
        context.py          # AgentContext, ContextWindow
        llm/                # LLM backends (Anthropic, OpenAI, Gemini, Mock)
        tools/              # Tool protocol, ToolRegistry, DatabaseTool, CacheTool, etc.
        prompts/            # Prompt templates for code generation and intent parsing
    application/
        pipeline.py         # DynamicPipeline, PipelineStage
    ops/
        base.py             # OpsAgent ABC, OpsHealthStatus
    testing/                # mock_llm, MockSandbox, assertions, fixtures, benchmarks
    cli/                    # Dev server, interactive console, version
examples/
    01_hello_agent/         # Minimal single-endpoint example (no LLM)
    02_ecommerce/           # Multi-endpoint with policies, tools, and approval
    03_openai_agent/        # OpenAI GPT — task tracker with harness safety
    04_anthropic_agent/     # Anthropic Claude — product catalogue agent
    05_gemini_agent/        # Google Gemini — support ticket agent
    06_full_stack/          # All features: pipeline, ops, A2A, REST compat, monitors
    07_comprehensive/       # Multi-feature composition per endpoint (DevOps domain)
```

## Requirements

- Python >= 3.13
- [Starlette](https://www.starlette.io/) >= 1.0 — ASGI foundation
- [Pydantic](https://docs.pydantic.dev/) >= 2.12 — Validation and schemas
- [structlog](https://www.structlog.org/) >= 25.0 — Structured logging
- [httpx](https://www.python-httpx.org/) >= 0.28 — Async HTTP client
- [anthropic](https://github.com/anthropics/anthropic-sdk-python) >= 0.89 — Claude API
- [openai](https://github.com/openai/openai-python) >= 2.30 — OpenAI API
- [google-genai](https://github.com/googleapis/python-genai) >= 1.70 — Gemini API

## License

[MIT](./LICENSE)
