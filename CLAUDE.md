# CLAUDE.md — AgenticAPI Development Guide

## Project Overview

AgenticAPI is a Python OSS framework that natively integrates coding agents into web applications. Built on Starlette/ASGI, it provides agent endpoints, harness engineering (policy enforcement, sandboxing, approval workflows), multi-LLM support, authentication, MCP compatibility, and auto-generated OpenAPI docs.

**In a nutshell**: FastAPI is for type-safe REST APIs. AgenticAPI is for harnessed agent APIs.

**Current status**: Phase 1 v0.1.0. Core: 81 source files, 10,609 LOC, 713 tests, 87% coverage, 12 examples. Extensions: `agenticapi-claude-agent-sdk` v0.1.0 (1,610 src LOC, 38 tests).

---

## Command Reference

### Setup

```bash
uv sync --group dev              # Install all dependencies
uv run agenticapi version        # Verify CLI works
pip install -e ".[mcp]"          # Optional: MCP support
```

### Testing

```bash
uv run pytest                                    # All 713 tests (613 unit+integration + 100 e2e)
uv run pytest --ignore=tests/benchmarks -q       # Skip benchmarks (faster)
uv run pytest tests/unit/harness/ -xvs           # Specific directory
uv run pytest --cov=src/agenticapi               # With coverage (87%)
uv run pytest tests/e2e/ -v                      # E2E tests for all 12 example apps
uv run pytest tests/benchmarks/                  # Benchmarks only
uv run pytest -m "not requires_llm"              # Skip LLM-dependent tests
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

**Current extensions:**

| Extension | Purpose | Deps |
|---|---|---|
| `agenticapi-claude-agent-sdk` | Wraps the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) for full planning + tool-use loops inside agent endpoints | `claude-agent-sdk>=0.1.58,<0.2` |

```bash
# Install the extension for development (no-deps so main package stays linked)
uv pip install -e extensions/agenticapi-claude-agent-sdk --no-deps

# Run extension tests (offline — uses a stub SDK module via conftest.py)
uv run pytest extensions/agenticapi-claude-agent-sdk/tests

# Type-check the extension
uv run mypy extensions/agenticapi-claude-agent-sdk/src
```

See:
- [development/extensions.md](development/extensions.md) — Extensions architecture and contribution guide
- [development/claude_agent_sdk_extension_plan.md](development/claude_agent_sdk_extension_plan.md) — Claude Agent SDK extension design rationale
- [extensions/agenticapi-claude-agent-sdk/README.md](extensions/agenticapi-claude-agent-sdk/README.md) — User-facing docs

---

## Architecture

See [development/architecture.md](development/architecture.md) for the full architecture document.

### Layer Structure

```
Interface Layer -> Harness Engine -> Agent Runtime -> Sandbox -> Response
```

### Request Flow

```
POST /agent/{name} {"intent": "..."}
  -> Authentication (if auth= configured)
  -> IntentParser.parse() -> Intent
  -> IntentScope check
  -> [LLM path]: CodeGenerator -> PolicyEvaluator -> StaticAnalysis
       -> ApprovalCheck -> ProcessSandbox -> Monitors -> Validators
       -> AuditRecorder -> AgentResponse
  -> [Handler path]: handler(intent, context) -> AgentResponse
  -> AgentTasks (background tasks run after response)
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

See [development/modules.md](development/modules.md) for the complete module reference.

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
| `MCPCompat` | `interface/compat/mcp.py` | MCP server (`pip install agenticapi[mcp]`) |
| `RESTCompat` | `interface/compat/rest.py` | REST route generation |
| `HtmxHeaders` | `interface/htmx.py` | HTMX request header detection (injected into handlers) |
| `htmx_response_headers()` | `interface/htmx.py` | Build HTMX response headers (HX-Trigger, etc.) |

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

See [development/security.md](development/security.md) for the full security model.

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

See [development/testing.md](development/testing.md) for the full testing guide.

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

1. Install: `pip install agenticapi[mcp]`
2. Mark endpoints: `@app.agent_endpoint(name="search", enable_mcp=True)`
3. Mount: `app.add_routes(expose_as_mcp(app))`
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
6. Reference: `extensions/agenticapi-claude-agent-sdk/` and `development/extensions.md`.

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

## Phase 2 Roadmap (Not Yet Implemented)

| Feature | Location | Description |
|---|---|---|
| A2A Server/Client | `interface/a2a/server.py`, `client.py` | Inter-agent HTTP communication |
| Service Discovery | `interface/a2a/discovery.py` | Agent registry and lookup |
| AdaptiveDataAccess | `application/data_access.py` | Multi-source data routing |
| BusinessRuleEngine | `application/business_rules.py` | NL-defined business rules |
| CrossDomainOptimizer | `application/cross_domain.py` | Cross-domain optimization |
| LogAnalyst | `ops/log_analyst.py` | Semantic log analysis |
| AutoHealer | `ops/auto_healer.py` | Automated incident recovery |
| PerformanceTuner | `ops/perf_tuner.py` | Runtime optimization |
| IncidentResponder | `ops/incident.py` | Incident management |
| ContainerSandbox | `harness/sandbox/container.py` | Kernel-level isolation |
| GraphQL compat | `interface/compat/graphql.py` | GraphQL schema exposure |
