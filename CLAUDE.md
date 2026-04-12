# CLAUDE.md — AgenticAPI Development Guide

## Project Overview

AgenticAPI is a Python OSS framework that natively integrates coding agents into web applications. Built on Starlette/ASGI, it provides agent endpoints, harness engineering (policy enforcement, sandboxing, approval workflows), multi-LLM support, authentication, MCP compatibility, and auto-generated OpenAPI docs.

**In a nutshell**: FastAPI is for type-safe REST APIs. AgenticAPI is for harnessed agent APIs.

**Current status** (as of Increment 9, 2026-04-12). Core: **118 Python
modules, ~21,944 LOC, 1,304 collected tests, 27 examples, 75 public
exports**. Extensions: `agentharnessapi[claude-agent-sdk]` (~1,610 src
LOC, 38 tests). **Phase A (control plane) is complete.** **Phase D
(typed handlers + DI) core is complete** including schema-driven OpenAPI
for typed `Intent[T]` request bodies (D7). Phases E / F have shipped
their cores. Phase C (learning plane) has shipped foundations (C1 memory,
C5 code cache, C6 eval harness). Phase B (safety) has shipped B5
prompt-injection detection and B6 `PIIPolicy`. The `mesh/` package
(AgentMesh, MeshContext) ships multi-agent orchestration with cycle
detection and budget propagation.

For the full plane-by-plane shipped / active / deferred matrix see
[`ROADMAP.md`](ROADMAP.md). For speculative forward tracks see
[`VISION.md`](VISION.md). For per-increment shipped-work log see
[`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md).

---

## Command Reference

### Setup

```bash
uv sync --group dev              # Install all dependencies
uv run agenticapi version        # Verify CLI works
pip install agentharnessapi[mcp]          # Optional: MCP support
```

### Testing

```bash
uv run pytest                                    # All 1,206 tests (unit + integration + e2e)
uv run pytest --ignore=tests/benchmarks -q       # Skip benchmarks (faster)
uv run pytest tests/unit/harness/ -xvs           # Specific directory
uv run pytest --cov=src/agenticapi               # With coverage
uv run pytest tests/e2e/ -v                      # E2E tests for all 27 example apps
uv run pytest tests/benchmarks/                  # Benchmarks only
uv run pytest -m "not requires_llm"              # Skip LLM-dependent tests
```

### CLI

```bash
uv run agenticapi version                        # Show version
uv run agenticapi dev --app myapp:app            # Development server
uv run agenticapi console --app myapp:app        # Interactive REPL
uv run agenticapi replay <trace_id> --app myapp:app           # Re-run an audit trace (A6)
uv run agenticapi eval --set evals/orders.yaml --app myapp:app   # Run an EvalSet (C6)
```

### Code Quality

```bash
uv run ruff format src/ tests/ examples/         # Format (examples included)
uv run ruff check src/ tests/ examples/          # Lint
uv run ruff check --fix src/ tests/ examples/    # Lint + auto-fix
uv run mypy src/agenticapi/                      # Type check (strict)

# Full CI check:
uv run ruff format --check src/ tests/ examples/ && uv run ruff check src/ tests/ examples/ && uv run mypy src/agenticapi/ && uv run pytest --ignore=tests/benchmarks
```

### Documentation

```bash
mkdocs serve -a 127.0.0.1:8001   # Live-reloading docs
mkdocs build                      # Static site in site/
mkdocs gh-deploy --force          # Deploy to GitHub Pages
```

### Pre-commit

```bash
uv run pre-commit install                        # Install git hooks
uv run pre-commit run --all-files                # Run all hooks manually
```

### Running Examples

```bash
agenticapi dev --app examples.01_hello_agent.app:app          # No LLM needed
agenticapi dev --app examples.06_full_stack.app:app           # Full features
agenticapi dev --app examples.08_mcp_agent.app:app            # MCP server
agenticapi dev --app examples.09_auth_agent.app:app           # Authentication
agenticapi console --app examples.02_ecommerce.app:app        # Interactive REPL
```

### Extensions

Independently-installable extensions live under `extensions/<name>/`
with their own `pyproject.toml`. Large or fast-moving dependencies
stay out of the core package and live in extension packages so users
only pay for what they use.

**Current extras:**

| Extra | Install | Purpose | Deps |
|---|---|---|---|
| `claude-agent-sdk` | `pip install agentharnessapi[claude-agent-sdk]` | Claude Agent SDK loop inside agent endpoints | `claude-agent-sdk>=0.1.58,<0.2` |
| `mcp` | `pip install agentharnessapi[mcp]` | MCP server support | `mcp>=1.27.0` |

```bash
# Run extension tests (offline — uses a stub SDK module via conftest.py)
uv run pytest tests/unit/ext/claude_agent_sdk/

# Type-check the extension
uv run mypy src/agenticapi/ext/
```

See:
- [docs/internals/extensions.md](docs/internals/extensions.md) — Extensions architecture
- [docs/internals/claude-agent-sdk-extension-plan.md](docs/internals/claude-agent-sdk-extension-plan.md) — Claude Agent SDK extension design rationale

---

## Architecture

See [docs/internals/current-state.md](docs/internals/current-state.md) first for implementation reality, then [docs/internals/architecture.md](docs/internals/architecture.md) for the full architecture document.

### Layer Structure

```
Interface Layer -> Harness Engine -> Agent Runtime -> Sandbox -> Response
                                              \-> Mesh Layer (AgentMesh, MeshContext)
```

### Request Flow

```
POST /agent/{name} {"intent": "..."}
  -> Authentication (if auth= configured)
  -> IntentParser.parse() -> Intent (or Intent[T] with structured output, D4)
  -> IntentScope check
  -> Route-level dependencies (D6)
  -> Dependency solver resolves handler params (D1)
  -> [LLM path]:
       -> BudgetPolicy.estimate_and_enforce (A4, pre-call)
       -> CodeGenerator.generate
          -> if approved-code cache hit: skip LLM (C5)
          -> else: LLMBackend.generate
       -> [Tool-first path (E4)]: if LLM picked a single tool,
              HarnessEngine.call_tool -> Policy.evaluate_tool_call
              -> Tool.invoke -> result (skips sandbox)
       -> [Codegen path]: PolicyEvaluator (all policies)
              -> StaticAnalysis -> ApprovalCheck -> ProcessSandbox
              -> Monitors -> Validators
       -> BudgetPolicy.record_actual (A4, post-call)
       -> AuditRecorder (A3, SqliteAuditRecorder optional)
       -> response_model validation (D5)
       -> AgentResponse
  -> [Streaming path (F1-F8)]:
       handler takes AgentStream param -> events yielded lazily
       -> SSE (F2) or NDJSON (F3) transport
       -> AutonomyPolicy live escalation (F6)
       -> stream.request_approval() in-request HITL (F5)
       -> StreamStore for resumable streams (F7)
  -> [Handler path]: handler(intent, context, ...) -> AgentResponse
  -> AgentTasks (background tasks run after response)

OpenTelemetry spans + metrics wrap every stage (A1/A2).
W3C traceparent propagated in and out (A5).
```

### Auto-Registered Routes

Every `AgenticApp` automatically provides:

| Route | Method | Description |
|---|---|---|
| `/agent/{name}` | POST | Agent endpoint (one per registered handler) |
| `/health` | GET | Health check with version, endpoints, ops agent status |
| `/capabilities` | GET | Structured metadata for all endpoints |
| `/openapi.json` | GET | OpenAPI 3.1.0 schema |
| `/docs` | GET | Swagger UI |
| `/redoc` | GET | ReDoc UI |

---

## Module Reference

See [docs/internals/modules.md](docs/internals/modules.md) for the complete module reference.

### Key Types

| Type | Location | Purpose |
|---|---|---|
| `AgenticApp` | `app.py` | Main ASGI app (like FastAPI) |
| `AgentRouter` | `routing.py` | Endpoint grouping (like APIRouter) |
| `Intent` | `interface/intent.py` | Parsed user request |
| `AgentResponse` | `interface/response.py` | Agent output with result, reasoning, trace |
| `AgentTasks` | `interface/tasks.py` | Background tasks (like FastAPI's BackgroundTasks) |
| `HarnessEngine` | `harness/engine.py` | Safety pipeline orchestrator |
| `CodePolicy` | `harness/policy/code_policy.py` | Import/eval/exec restrictions |
| `DataPolicy` | `harness/policy/data_policy.py` | SQL table/column access control |
| `ResourcePolicy` | `harness/policy/resource_policy.py` | CPU/memory/time limits |
| `RuntimePolicy` | `harness/policy/runtime_policy.py` | AST complexity limits |
| `ProcessSandbox` | `harness/sandbox/process.py` | Isolated code execution |
| `ApprovalWorkflow` | `harness/approval/workflow.py` | Human-in-the-loop approval |
| `AuditRecorder` | `harness/audit/recorder.py` | Execution trace recording |
| `LLMBackend` | `runtime/llm/base.py` | Protocol for LLM providers |
| `Tool` | `runtime/tools/base.py` | Protocol for agent tools |
| `DynamicPipeline` | `application/pipeline.py` | Middleware-like stage composition |
| `OpsAgent` | `ops/base.py` | Operational agent base class |
| `Authenticator` | `security.py` | Auth scheme + verify function |
| `APIKeyHeader` | `security.py` | Extract API key from header |
| `HTTPBearer` | `security.py` | Extract Bearer token |
| `FileResult` | `interface/response.py` | File download wrapper (bytes, path, or streaming) |
| `HTMLResult` | `interface/response.py` | HTML response (like FastAPI's `HTMLResponse`) |
| `PlainTextResult` | `interface/response.py` | Plain text response |
| `UploadFile` | `interface/upload.py` | Uploaded file data (filename, content, size) |
| `UploadedFiles` | `interface/upload.py` | Handler param type for auto-injected uploaded files |
| `MCPCompat` | `interface/compat/mcp.py` | MCP server (`pip install agentharnessapi[mcp]`) |
| `RESTCompat` | `interface/compat/rest.py` | REST route generation |
| `HtmxHeaders` | `interface/htmx.py` | HTMX request header detection (injected into handlers) |
| `htmx_response_headers()` | `interface/htmx.py` | Build HTMX response headers (HX-Trigger, etc.) |
| `Depends` / `Dependency` | `dependencies/depends.py` | FastAPI-style dependency injection for handler params |
| `@tool` | `runtime/tools/decorator.py` | Declare tools from plain async functions with type hints |
| `BudgetPolicy` | `harness/policy/budget_policy.py` | Per-request/session/user cost ceilings |
| `PricingRegistry` | `harness/policy/pricing.py` | LLM token-cost pricing table for budget enforcement |
| `BudgetExceeded` | `exceptions.py` | Raised when a request exceeds its cost budget (HTTP 402) |
| `PromptInjectionPolicy` | `harness/policy/prompt_injection_policy.py` | 10 built-in detection rules; `disabled_categories=` + `extra_patterns=`; shadow mode |
| `PIIPolicy` / `PIIHit` / `redact_pii` | `harness/policy/pii_policy.py` | Detect / redact / block email, phone, SSN, credit card (Luhn), IBAN, IPv4; `evaluate_tool_call` hook; standalone `redact_pii()` utility (B6) |
| `AutonomyPolicy` / `EscalateWhen` / `AutonomySignal` | `harness/policy/autonomy_policy.py` | Declarative escalation rules evaluated mid-stream (F6) |
| `AgentStream` / `AgentEvent` | `interface/stream.py` | Streaming handler param + 8 typed event types (F1) |
| `StreamStore` / `InMemoryStreamStore` | `interface/stream_store.py` | Persisted stream state for resume endpoint (F7) |
| `ApprovalRegistry` | `interface/approval_registry.py` | In-request HITL approval ticket registry (F5) |
| `MemoryStore` / `InMemoryMemoryStore` / `SqliteMemoryStore` | `runtime/memory/*` | Agent memory protocol + persistent backend; `MemoryKind` = episodic / semantic / procedural (C1) |
| `CodeCache` / `InMemoryCodeCache` / `CachedCode` | `runtime/code_cache.py` | Deterministic approved-code cache with LRU + TTL (C5) |
| `EvalSet` / judges | `evaluation/*` | YAML eval harness + 5 built-in judges (C6) |
| `SqliteAuditRecorder` | `harness/audit/sqlite_store.py` | Persistent audit store with `iter_since()` replay support (A3) |
| `AgentMesh` | `mesh/mesh.py` | Multi-agent orchestration container with `@role` + `@orchestrator` decorators |
| `MeshContext` / `MeshCycleError` | `mesh/context.py` | Request-scoped inter-role call context with cycle detection + budget propagation |
| `RetryConfig` / `with_retry` | `runtime/llm/retry.py` | Exponential-backoff retry wrapper for transient LLM provider errors |
| Observability | `observability/tracing.py`, `metrics.py`, `propagation.py`, `semconv.py` | OpenTelemetry spans + metrics + traceparent (A1/A2/A5, no-op without OTel) |

### Custom Response Types

Handlers can return non-JSON responses by using result wrapper types:

```python
from agenticapi import HTMLResult, PlainTextResult, FileResult

# HTML page
@app.agent_endpoint(name="dashboard")
async def dashboard(intent, context):
    return HTMLResult(content="<h1>Dashboard</h1><p>Welcome!</p>")

# Plain text
@app.agent_endpoint(name="status")
async def status(intent, context):
    return PlainTextResult(content="OK")

# File download
@app.agent_endpoint(name="export")
async def export(intent, context):
    return FileResult(content=b"csv,data", media_type="text/csv", filename="export.csv")
```

You can also return any Starlette `Response` subclass directly (HTMLResponse, StreamingResponse, etc.).

### AgenticApp Constructor

```python
AgenticApp(
    title="AgenticAPI",
    version="0.1.0",
    description="",
    harness=None,           # HarnessEngine
    llm=None,               # LLMBackend
    tools=None,             # ToolRegistry
    middleware=None,         # list[Middleware]
    auth=None,              # Authenticator (app-wide default)
    docs_url="/docs",       # None to disable
    redoc_url="/redoc",     # None to disable
    openapi_url="/openapi.json",  # None to disable all docs
)
```

### Middleware (ASGI-level)

```python
from starlette.middleware.cors import CORSMiddleware

app = AgenticApp(title="My Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Middleware wraps the entire ASGI app. For agent-specific request enrichment, use `DynamicPipeline` instead.

---

## Coding Conventions

### Python

- **Python 3.13+** target. Use `match`, `type` statements, modern type syntax.
- **Type hints on all public APIs.** Internal code: encouraged.
- **Docstrings**: Google style on all public APIs.
- **Format**: `ruff format` (line length 120).
- **Lint**: `ruff check`. **Types**: `mypy --strict`.
- **async-first**: Use `async def` for I/O. Sync for pure computation.

### Data Models

| Use Case | Type | Why |
|---|---|---|
| User-facing config/schema | `pydantic.BaseModel` | Validation, JSON Schema |
| Internal immutable data | `@dataclass(frozen=True, slots=True)` | Lightweight, hashable |
| Internal mutable data | `@dataclass(slots=True)` | Lightweight |
| Enum values | `StrEnum` | String-comparable |
| Pluggable interfaces | `Protocol` | No inheritance dependency |
| Internal inheritance | `ABC` | For SandboxRuntime, OpsAgent |

### Naming

```python
module_name.py          # snake_case
class ClassName:        # PascalCase
async def func_name():  # snake_case
DEFAULT_CONSTANT = 42   # UPPER_SNAKE_CASE
def _private_method():  # _prefix for private
```

### Exceptions

- User-visible errors -> `InterfaceError` (mapped to HTTP 4xx)
- Authentication failures -> `AuthenticationError` (401), `AuthorizationError` (403)
- Internal control flow -> `HarnessError` (handled by harness)
- Unexpected errors -> `AgentRuntimeError` (logged, incident-tracked)
- **Never swallow exceptions** (`except Exception: pass` is forbidden)

### Logging

```python
import structlog
logger = structlog.get_logger(__name__)

logger.info("intent_parsed", action=intent.action, confidence=intent.confidence)
logger.warning("policy_near_limit", cpu_usage=0.78, threshold=0.80)
logger.error("execution_failed", error=str(e), trace_id=ctx.trace_id)
```

---

## Security

See [docs/internals/security.md](docs/internals/security.md) for the full security model.

### Authentication

```python
from agenticapi.security import APIKeyHeader, Authenticator, AuthUser

api_key = APIKeyHeader(name="X-API-Key")

async def verify(credentials):
    if credentials.credentials == "secret":
        return AuthUser(user_id="u1", username="alice", roles=["admin"])
    return None

auth = Authenticator(scheme=api_key, verify=verify)

# Per-endpoint
@app.agent_endpoint(name="orders", auth=auth)

# Or app-wide default
app = AgenticApp(auth=auth)
```

### Defense in Depth (7 layers)

1. **Prompt design** — XML-escaped user input (`html.escape()`)
2. **Static AST analysis** — forbidden imports, eval/exec, getattr, file I/O
3. **Policy evaluation** — CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
4. **Approval workflow** — human-in-the-loop with async lock
5. **Process sandbox** — base64 code transport, subprocess isolation, timeout
6. **Post-execution** — resource monitors, output validators
7. **Audit trail** — bounded ExecutionTrace recording

---

## Testing

See [docs/internals/testing.md](docs/internals/testing.md) for the full testing guide.

### Test-First Development

```bash
# 1. Write test
# 2. Verify it fails (red)
# 3. Implement minimum to pass (green)
# 4. Refactor
# 5. ruff format + ruff check + mypy
```

### Performance Targets

| Component | Target |
|---|---|
| IntentParser.parse() (keyword) | < 50ms |
| PolicyEvaluator.evaluate() | < 15ms |
| Static analysis (1000 lines) | < 50ms |
| ProcessSandbox startup | < 100ms |

---

## Examples

See [examples/README.md](examples/README.md) for the full examples guide.

| Example | LLM | Features |
|---|---|---|
| `01_hello_agent` | None | Minimal endpoint |
| `02_ecommerce` | None | Routers, policies, approval, tools |
| `03_openai_agent` | OpenAI GPT | Full harness pipeline |
| `04_anthropic_agent` | Anthropic Claude | Policies, ResourcePolicy |
| `05_gemini_agent` | Google Gemini | Sessions, CacheTool |
| `06_full_stack` | Configurable | Everything: pipeline, ops, A2A, REST compat, monitors |
| `07_comprehensive` | Configurable | Multi-feature composition per endpoint (DevOps platform) |
| `08_mcp_agent` | None | MCP server: `enable_mcp=True`, `expose_as_mcp()` |
| `09_auth_agent` | None | Authentication: `APIKeyHeader`, `Authenticator`, `auth=` |
| `10_file_handling` | None | File upload/download: `UploadedFiles`, `FileResult`, streaming |
| `11_html_responses` | None | Custom responses: `HTMLResult`, `PlainTextResult`, `FileResult` |
| `12_htmx` | None | HTMX integration: `HtmxHeaders`, partial page updates, `htmx_response_headers` |
| `13_claude_agent_sdk` | Claude Agent SDK | Full agentic loop via `agentharnessapi[claude-agent-sdk]` |
| `14_dependency_injection` | None | `Depends()`, nested deps, `yield` teardown, `@tool` decorator |
| `15_budget_policy` | None | `BudgetPolicy`, `PricingRegistry`, HTTP 402, spend tracking |
| `16_observability` | None | OTEL tracing, Prometheus `/metrics`, `SqliteAuditRecorder` |
| `17_typed_intents` | None | `Intent[T]`, Pydantic payload validation, structured output |
| `18_rest_interop` | None | `response_model`, `RESTCompat`, schema enforcement |
| `19_native_function_calling` | None | `ToolCall`, native function calling, multi-turn loop |
| `20_streaming_release_control` | None | `AgentStream`, SSE/NDJSON, `request_approval()`, `AutonomyPolicy` |
| `21_persistent_memory` | None | `MemoryStore`, `SqliteMemoryStore`, `MemoryKind`, GDPR forget |
| `22_safety_policies` | None | `PromptInjectionPolicy`, `PIIPolicy`, shadow mode, `redact_pii()` |
| `23_eval_harness` | None | `EvalSet`, `EvalRunner`, 5 built-in judges, YAML eval sets |
| `24_code_cache` | None | Approved-code cache to skip LLM on repeat intents |
| `24_multi_agent_pipeline` | None | `AgentMesh`, `@mesh.role`, `@mesh.orchestrator`, `MeshContext.call()` |
| `25_harness_playground` | None | Full harness with autonomy, safety, streaming |
| `26_dynamic_pipeline` | None | `DynamicPipeline`, per-request stage selection |

---

## How to Extend AgenticAPI

### Adding a New Policy

1. Create `src/agenticapi/harness/policy/my_policy.py` inheriting from `Policy` (in `base.py`)
2. Implement `evaluate(*, code, intent_action, intent_domain, **kwargs) -> PolicyResult`
3. Export from `harness/policy/__init__.py` and `harness/__init__.py`
4. Add tests in `tests/unit/harness/test_my_policy.py`
5. Optionally export from `src/agenticapi/__init__.py` if public API

### Adding a New Tool

1. Create `src/agenticapi/runtime/tools/my_tool.py` implementing the `Tool` protocol
2. Implement `definition` property -> `ToolDefinition` and `async invoke(**kwargs)`
3. Export from `runtime/tools/__init__.py`
4. Add tests in `tests/unit/runtime/test_my_tool.py`
5. Reference: `database.py` for the standard pattern

### Adding a New LLM Backend

1. Create `src/agenticapi/runtime/llm/my_backend.py` implementing `LLMBackend` protocol
2. Implement `generate()`, `generate_stream()`, `model_name` property
3. Constructor: accept `api_key`, `model`, `max_tokens`, `timeout` parameters
4. Read API key from env var with explicit parameter override
5. Export from `runtime/llm/__init__.py`
6. Add tests in `tests/unit/runtime/test_my_backend.py`
7. Reference: `anthropic.py`, `openai.py`, `gemini.py`

### Adding a New Example

1. Create `examples/NN_my_example/app.py` (no `__init__.py` needed)
2. Include docstring with Prerequisites, Run command, and curl test commands
3. Use `TYPE_CHECKING` for `AgentContext` import
4. Use broad `IntentScope` wildcards (`*.read`, `*.analyze`) — LLMs may classify domains unpredictably
5. Pass `tools=tools` to `AgenticApp()` if using tools with LLM
6. Add E2E tests in `tests/e2e/test_examples.py`
7. Update `examples/README.md`

### Exposing Endpoints via MCP

1. Install: `pip install agentharnessapi[mcp]`
2. Mark endpoints: `@app.agent_endpoint(name="search", enable_mcp=True)`
3. Mount: `expose_as_mcp(app)`
4. Test: `npx @modelcontextprotocol/inspector http://localhost:8000/mcp`
5. Reference: `examples/08_mcp_agent/app.py`

### Adding Authentication

1. Choose a scheme: `APIKeyHeader`, `APIKeyQuery`, `HTTPBearer`, or `HTTPBasic`
2. Write a `verify` function: `async (AuthCredentials) -> AuthUser | None`
3. Create `Authenticator(scheme=..., verify=...)`
4. Attach per-endpoint: `@app.agent_endpoint(name="x", auth=auth)` or app-wide: `AgenticApp(auth=auth)`
5. Access user in handler via `context.auth_user`
6. Reference: `examples/09_auth_agent/app.py`

### Adding File Upload/Download

1. **Upload**: Add `UploadedFiles` parameter to handler -> client sends `multipart/form-data`
2. **Download**: Return `FileResult(content=..., media_type=..., filename=...)` from handler
3. `FileResult.content` accepts `bytes` (inline), `str` (file path), or async iterable (streaming)
4. Handlers can also return a raw Starlette `Response` for full control
5. Reference: `examples/10_file_handling/app.py`

### Adding Custom Response Types

1. Return `HTMLResult(content="<h1>Hello</h1>")` for HTML pages
2. Return `PlainTextResult(content="OK")` for plain text
3. Return `FileResult(content=..., media_type=..., filename=...)` for file downloads
4. Return any Starlette `Response` subclass for full control
5. Reference: `examples/11_html_responses/app.py`

### Building HTMX Apps

1. Add `HtmxHeaders` parameter to handlers: auto-injected with parsed HTMX headers
2. Check `htmx.is_htmx` to decide between full page and fragment response
3. Return `HTMLResult(content=fragment)` for HTMX requests
4. Use `htmx_response_headers(trigger="event")` for client-side event triggers
5. Reference: `examples/12_htmx/app.py`

### Using Dependency Injection

FastAPI-style `Depends()` for handler parameters. Supports sync + async functions, `yield` cleanup, and nested dependencies:

```python
from agenticapi import Depends

async def get_db():
    async with engine.connect() as conn:
        yield conn

@app.agent_endpoint(name="orders")
async def orders(intent, context, db=Depends(get_db)):
    ...
```

1. Declare the dependency as a plain callable (sync or async, may `yield`)
2. Annotate the handler param with `= Depends(provider)`
3. The framework scans and solves the dependency graph at registration time
4. Reference: `src/agenticapi/dependencies/`

### Declaring Tools via `@tool`

Avoid the verbose `Tool` protocol — write a typed async function:

```python
from agenticapi import tool

@tool(description="Look up a user by ID")
async def get_user(user_id: int) -> dict:
    return {"id": user_id, "name": "Alice"}

registry.register(get_user)
```

The decorator infers `parameters_schema` from type hints and the docstring.

1. Use plain type hints (`int`, `str`, `list[int]`, etc.) — schema is generated
2. Docstring first line becomes the tool description if not specified
3. Async and sync functions both work
4. Reference: `src/agenticapi/runtime/tools/decorator.py`

### Adding Cost Budget Enforcement

`BudgetPolicy` is a cost-governance primitive with request/session/user/endpoint scopes. In the current implementation, the real integration path is explicit around LLM calls via `estimate_and_enforce(...)` and `record_actual(...)`.

```python
from agenticapi import BudgetPolicy, PricingRegistry, HarnessEngine

pricing = PricingRegistry.default()  # built-in pricing for Claude, GPT, Gemini
budget = BudgetPolicy(
    pricing=pricing,
    max_per_request_usd=0.50,
    max_per_session_usd=5.00,
)
harness = HarnessEngine(policies=[code_policy, budget])
```

Exceeded budgets raise `BudgetExceeded` -> HTTP **402 Payment Required**. See `docs/internals/budgets.md` for the current explicit integration pattern and caveats.

### Adding Observability (OpenTelemetry)

Tracing and metrics are opt-in and degrade to no-op when `opentelemetry-api` is not installed:

```python
from agenticapi.observability import configure_tracing, configure_metrics

configure_tracing(service_name="my-agent")
configure_metrics(service_name="my-agent")
```

Core request metrics and tracing are wired in, and the helper APIs cover policy denials, budget blocks, tool calls, and LLM usage. Automatic coverage is still partial for some newer execution paths, so use the `record_*` helpers explicitly when extending the framework.

See [docs/internals/observability.md](docs/internals/observability.md) for the full semconv and metric catalogue.

### Creating a New Extension Package

Extensions live under `extensions/<package-name>/` with their own `pyproject.toml` and are published separately from core.

1. Create `extensions/my-extension/` with this layout:
   ```
   extensions/my-extension/
       pyproject.toml
       README.md
       src/my_extension/
           __init__.py        # Public API via __all__
           py.typed           # PEP 561 marker
       tests/
           conftest.py        # Stub optional heavy deps if needed
           test_*.py
       examples/
   ```
2. `pyproject.toml`: depend on `agenticapi>=0.1.0` plus whatever heavy/fast-moving library you're wrapping. Pin carefully (e.g., `>=X.Y,<X.Y+1`).
3. Use **lazy imports** for the wrapped library so `import my_extension` never fails even when the optional dep is absent. Raise a friendly `*NotInstalledError` on first use.
4. Tests must run **offline**: install a stub module in `conftest.py` that mimics the wrapped library's public surface.
5. Errors should inherit from `agenticapi.AgenticAPIError` so callers can catch both core and extension errors uniformly.
6. Reference: `src/agenticapi/ext/claude_agent_sdk/` and `docs/internals/extensions.md`.

## Forward Tracks — Implementation Guide

Three forward tracks are defined in [`VISION.md`](VISION.md). This
section provides the implementation-level guidance a Claude Code session
needs to execute them. For the strategic rationale see
[`PROJECT.md`](PROJECT.md) > Strategic Forward Tracks. Full task-level
specs live in [`VISION.md`](VISION.md).

### Track summaries

| Track | One-line summary | VISION.md section |
|---|---|---|
| **1 — Agent Mesh** | Governed multi-agent orchestration with budget propagation, approval bubbling, and audit linkage | Track 1 (Phases G + M) |
| **2 — Hardened Trust** | Declarative capability grants, kernel-isolated sandbox, secret substitution, code attestation, `production=True` mode | Track 2 (Phases I + T) |
| **3 — Self-Improving Flywheel** | Outcome feedback, skill mining from audit traces, adaptive routing, prompt auto-tuning | Track 3 (Phases H + L) |

### Substrate already shipped (per track)

**Track 1 (Mesh):** D1 (DI scanner for `MeshContext` injection), D4
(`Intent[T]` for typed role payloads), A3 (SqliteAuditRecorder for
linked audit rows), A4 (BudgetPolicy for scope propagation), A5
(traceparent for distributed mesh traces), F1 (AgentStream for nested
events), F5 (ApprovalRegistry for bubbling).

**Track 2 (Trust):** B5 (PromptInjectionPolicy), B6 (PIIPolicy), E4
(`evaluate_tool_call` hook for per-tool capability enforcement), A1
(OTEL for sandbox span events), A3 (SqliteAuditRecorder for attestation
persistence), `SandboxRuntime` ABC in `harness/sandbox/base.py`.

**Track 3 (Flywheel):** A3 (SqliteAuditRecorder — the feedstock), A6
(replay primitive for evaluating prompt variants), C1 (MemoryStore for
long-lived experience records), C5 (approved-code cache, subsumed by
SkillMiner promotions), C6 (EvalSet for PromptCompiler objective
scoring), E4 (tool-first execution path — promoted skills become tools),
D5 (response_model for outcome classification).

### Execution ordering

```
MeshEnvelope zero increment (shared propagation type)
    -> Track 1 (Agent Mesh, ~4-6 days)
    -> Track 2 (Hardened Trust, ~5-7 days)
    -> Track 3 (Flywheel, ~6-8 days)
```

The `MeshEnvelope` type ships first so all three tracks consume the same
propagation envelope and cannot diverge.

### Per-task prompt template

When starting any task from `VISION.md` or the Implementation Blueprints
above, use this structure:

```
1. Read the task spec (VISION.md > Track N, or the Blueprint above).
2. Read development/ docs for the relevant subsystem architecture.
3. Implement the minimum to pass the "Done when" checklist.
4. Run the quality gate:
   uv run ruff format --check src/ tests/ examples/ && \
   uv run ruff check src/ tests/ examples/ && \
   uv run mypy src/agenticapi/ && \
   uv run pytest --ignore=tests/benchmarks
5. Update ROADMAP.md + IMPLEMENTATION_LOG.md in the same commit.
6. If the task ships new public API names, update the Key Types table
   in this file.
```

---

## CI/CD

### GitHub Actions (`.github/workflows/ci.yml`)

| Job | Trigger | What it does |
|---|---|---|
| `pre-commit` | Push + PR to `main` | Runs all pre-commit hooks |
| `lint` | Push + PR to `main` | `ruff format --check` + `ruff check` |
| `typecheck` | Push + PR to `main` | `mypy --strict` |
| `test` | Push + PR to `main` | `pytest` (unit + integration, excludes benchmarks and e2e), uploads coverage XML |
| `docs` | Push to `main` only | `mkdocs gh-deploy` (after lint/typecheck/test pass) |

### Pre-commit Hooks (`.pre-commit-config.yaml`)

| Hook | Source | What it checks |
|---|---|---|
| `ruff-format` | `astral-sh/ruff-pre-commit` | Code formatting |
| `ruff` | `astral-sh/ruff-pre-commit` | Lint with auto-fix |
| `mypy` | `pre-commit/mirrors-mypy` | Type checking |

---

## Commit Conventions

[Conventional Commits](https://www.conventionalcommits.org/):

```
feat(interface): add IntentParser with LLM-based parsing
fix(harness): fix policy evaluation order
test(sandbox): add benchmark for ProcessSandbox startup
security(sandbox): add AST checks for __import__ patterns
```

Scopes: `interface`, `harness`, `runtime`, `application`, `ops`, `cli`, `testing`, `deps`, `docs`

---

## Implementation Blueprints

File-level task specs for the three immediate strategic priorities
identified in [`PROJECT.md`](PROJECT.md) > Immediate Strategic Priorities.
Each task is designed to be picked up by a single Claude Code session
using the per-task prompt template below.

### Element 1: Native Function Calling (E8)

**Task E8-A: Anthropic `tool_use` round-trip.**
File: `src/agenticapi/runtime/llm/anthropic.py`. Parse `ToolUseBlock`
from `message.content` into `ToolCall` objects on `LLMResponse`. Set
`finish_reason = "tool_calls"` when `stop_reason == "tool_use"`.
Add retry (3x with jitter) for `RateLimitError`, `APITimeoutError`.
Tests: `tests/unit/runtime/llm/test_anthropic_tool_calls.py`.

**Task E8-B: OpenAI `tool_calls` round-trip.**
File: `src/agenticapi/runtime/llm/openai.py`. Parse
`response.choices[0].message.tool_calls` into `ToolCall` objects.
Pass `finish_reason` from `choices[0].finish_reason`.
Add retry for `RateLimitError`, `APITimeoutError`.
Tests: `tests/unit/runtime/llm/test_openai_tool_calls.py`.

**Task E8-C: Gemini `function_calling` round-trip.**
File: `src/agenticapi/runtime/llm/gemini.py`. Build
`function_declarations` from `prompt.tools`. Parse
`part.function_call` from `response.candidates[0].content.parts`.
Add retry for `ResourceExhausted`, `ServiceUnavailable`.
Tests: `tests/unit/runtime/llm/test_gemini_tool_calls.py`.

**Task E8-D: `tool_choice` on `LLMPrompt`.**
File: `src/agenticapi/runtime/llm/base.py`. Add `tool_choice: str |
dict[str, str] | None = None` to `LLMPrompt`. Update `MockBackend`
to honour `tool_choice="required"`.

**Task E8-E: Integration tests (gated on env vars).**
Files: `tests/integration/llm/test_real_{anthropic,openai,gemini}.py`.
Each sends a prompt with one tool, asserts `tool_calls` is non-empty.
Gated with `@pytest.mark.skipif(not os.environ.get("..._API_KEY"))`.

**Task E8-F: Update examples 03/04/05.**
Add a handler in each LLM example that exercises tool-first dispatch
with a real provider. Falls back to direct-handler mode without a key.

**Task RETRY-1: Retry wrapper.**
File: `src/agenticapi/runtime/llm/retry.py`. `RetryConfig` dataclass
+ `with_retry(fn, config)` async wrapper. Each backend's constructor
accepts `retry: RetryConfig`. Tests: `tests/unit/runtime/llm/test_retry.py`.

### Element 2: Multi-Agent Mesh (remote transport)

**Task MESH-HTTP: `HttpTransport` for remote mesh peers.**
File: `src/agenticapi/mesh/transport.py`. `HttpTransport(peers={...})`
that calls another AgenticAPI instance with `traceparent` + delegation
headers. Falls back to `LocalTransport` (already shipped).

**Task MESH-BUDGET: Cross-agent `BudgetScope` propagation.**
File: `src/agenticapi/harness/policy/budget_policy.py`. Add
`BudgetScope(parent, key, limit_usd)` so sub-agent costs debit the
parent's shared wallet. Tests: budget exhaustion across 2 hops.

**Task MESH-APPROVAL: Approval bubbling.**
File: `src/agenticapi/interface/approval_registry.py`. Sub-agent
`request_approval()` resolves against the parent's ticket so the
operator sees one item, not N.

### Element 3: Init Templates

**Task INIT-CHAT: `--template chat` variant.**
Generates an app with `AgentStream` + `streaming="sse"` +
`AutonomyPolicy` with one `EscalateWhen` rule. Handler emits
`thought`, `partial`, `final` events.

**Task INIT-TOOLS: `--template tool-calling` variant.**
Generates an app with 3 `@tool` functions, uses the tool-first
path, falls back to `MockBackend` with pre-queued responses.

### Per-task prompt template for Claude Code

```
You are implementing AgenticAPI task {TASK_ID}.
Read CLAUDE.md (this file) before doing anything else.

Your job:
1. Follow the task's file list and API sketch exactly.
2. Implement with `mypy --strict` compliance.
3. Add the tests listed.
4. Run quality gates:
   uv run ruff format --check src/ tests/ examples/ \
     && uv run ruff check src/ tests/ examples/ \
     && uv run mypy src/agenticapi/ \
     && uv run pytest --ignore=tests/benchmarks -q
5. Fix any failures before reporting done.
6. Update ROADMAP.md + IMPLEMENTATION_LOG.md (durability rule).

Do not invent features beyond the task description.
```

---

## Roadmap

The **single source of execution truth** is [`ROADMAP.md`](ROADMAP.md).

- What's shipped: `ROADMAP.md` > Shipped (Phase D / E / F / A / B / C
  tables with per-task increment numbers and links to
  `IMPLEMENTATION_LOG.md`).
- What's next: `ROADMAP.md` > Active.
- What's parked and why: `ROADMAP.md` > Deferred.
- Original Phase 2 items and their current mapping:
  [`VISION.md`](VISION.md) > Historical Appendix.
- Speculative future tracks (Agent Mesh, Hardened Trust, Self-Improving
  Flywheel): [`VISION.md`](VISION.md).

---

## Documentation Map

The project has four root planning docs, an append-only log, one
mkdocs site, and one archive:

| File | Job |
|---|---|
| [`README.md`](README.md) | User landing page: positioning, 5-minute tour, install |
| [`PROJECT.md`](PROJECT.md) | Stable product vision + design principles + architecture overview + harness concept |
| [`ROADMAP.md`](ROADMAP.md) | **Living status doc.** Shipped / Active / Deferred / Superseded tables for every plane |
| [`VISION.md`](VISION.md) | Speculative forward tracks (Mesh, Trust, Flywheel) + historical appendix |
| [`CLAUDE.md`](CLAUDE.md) | **This file.** Developer guide: commands, conventions, module map, extending |
| [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md) | Append-only log of shipped increments |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contributor onboarding (setup, tests, commit conventions) |
| [`SECURITY.md`](SECURITY.md) | Vulnerability reporting + security model summary |
| [`docs/`](docs/) | mkdocs site: Getting Started, Guides, API Reference, Internals |
| [`development/`](development/) | Internal engineering docs for contributors + Claude Code (architecture, modules, testing, extending, security) |

### The durability rule

**Every `IMPLEMENTATION_LOG.md` entry must update `ROADMAP.md` in the
same commit.** This is the one rule that keeps the shipped / active /
deferred tables from going stale. When you finish an increment:

1. Append a new `# Increment N — ...` section to `IMPLEMENTATION_LOG.md`.
2. Move the relevant tasks from `ROADMAP.md` > Active (or Deferred or
   Superseded) into the correct **Shipped** table with the increment
   number and a link to the log anchor.
3. Refresh the "At a glance" status column and the metrics footer in
   `ROADMAP.md`.
4. If the increment shipped new public API names, also update the "Key
   Types" table in this file.
5. If the increment shipped new guides or internals docs, update
   [`mkdocs.yml`](mkdocs.yml) > `nav`.
