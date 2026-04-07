# CLAUDE_EN.md — AgenticAPI Development Guide

## Project Overview

AgenticAPI is a Python open-source framework that natively integrates coding agents into every layer of web applications. Drawing on FastAPI/Starlette's architectural patterns, it introduces three new concepts: agent endpoints, harness engineering, and ops agents.

**In a nutshell**: Just as FastAPI is a framework for easily building type-safe REST APIs, AgenticAPI is a framework for easily building harnessed agent APIs.

---

## Command Reference

### Build & Dependencies

```bash
# Initial setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Adding dependencies (after updating pyproject.toml)
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Specific module
pytest tests/unit/test_intent.py
pytest tests/unit/harness/

# Specific test function
pytest tests/unit/test_intent.py::test_parse_simple_intent -xvs

# With coverage
pytest --cov=src/agenticapi --cov-report=term-missing

# Integration tests (no external services required)
pytest tests/integration/ -m "not requires_llm"

# Integration tests including LLM calls (requires ANTHROPIC_API_KEY)
pytest tests/integration/ -m "requires_llm"

# Benchmarks
pytest tests/benchmarks/ --benchmark-only
```

### Linter & Formatter

```bash
# Format
ruff format src/ tests/

# Lint
ruff check src/ tests/

# Lint (auto-fix)
ruff check --fix src/ tests/

# Type check
mypy src/agenticapi/

# All checks at once (CI equivalent)
ruff format --check src/ tests/ && ruff check src/ tests/ && mypy src/agenticapi/ && pytest
```

### Development Server

```bash
# Start dev server (using examples)
python -m agenticapi dev --app examples.01_hello_agent.app:app

# Interactive console
python -m agenticapi console --app examples.01_hello_agent.app:app
```

---

## Architecture

### Layer Structure

```
Interface Layer (ingress) → Harness Engine (control) → Agent Runtime (execution) → Application Layer (processing) → Ops Layer (operations)
```

All requests are processed in this order. Each layer is independently testable, and dependencies flow in one direction only — top to bottom.

### Module Dependencies (strictly enforced)

```
agenticapi.interface  → agenticapi.harness, agenticapi.runtime
agenticapi.harness    → agenticapi.runtime (interface portion only)
agenticapi.runtime    → external dependencies only (LLM SDK, DB driver, etc.)
agenticapi.application→ agenticapi.runtime, agenticapi.harness
agenticapi.ops        → agenticapi.runtime, agenticapi.harness, agenticapi.application
agenticapi.cli        → all modules
agenticapi.testing    → all modules
```

**Prohibited dependency directions:**
- `runtime` → `interface` (runtime must not know about the interface)
- `harness` → `interface` (harness must not know about the interface)
- `harness` → `application` (harness must not know about the application layer)
- `runtime` → `ops` (runtime must not know about the ops layer)

### Mapping to FastAPI/Starlette

AgenticAPI follows FastAPI/Starlette's design patterns. Always keep these correspondences in mind during implementation.

| FastAPI/Starlette | AgenticAPI | Notes |
|---|---|---|
| `FastAPI` | `AgenticApp` | Main application class. Holds Starlette internally |
| `@app.get("/path")` | `@app.agent_endpoint(name=...)` | Endpoint registration decorator |
| `APIRouter` | `AgentRouter` | Endpoint grouping |
| `Request` | `Intent` | Input abstraction. Intent is created by transforming an HTTP Request |
| `Response` | `AgentResponse` | Output abstraction |
| `Depends()` | `HarnessDepends()` | Dependency injection. Harness policies are also injected via DI |
| Middleware stack | `DynamicPipeline` | Dynamic version of middleware composition |
| `BackgroundTasks` | `AgentTasks` | Background processing by agents |
| Pydantic model | Pydantic model | Schema definitions are inherited as-is |
| ASGI interface | ASGI interface | Built on top of ASGI. Can be started directly with uvicorn |

### Structure as an ASGI Application

AgenticApp is an ASGI application. It must be directly startable with uvicorn.

```python
# User code
app = AgenticApp()

# Startup
# uvicorn myapp:app --host 0.0.0.0 --port 8000

# AgenticApp.__call__ implements the ASGI interface
class AgenticApp:
    async def __call__(self, scope, receive, send):
        # Dispatch to the internal Starlette app
        await self._starlette_app(scope, receive, send)
```

### HTTP Request to Intent Conversion Flow

```
HTTP Request (ASGI scope/receive)
    ↓
Starlette Router (URL/method-based routing)
    ↓ For POST /agent/{endpoint_name}
AgentEndpointHandler
    ↓
IntentParser.parse(request_body) → Intent object created
    ↓
HarnessEngine.evaluate(intent, policies) → allow/deny/pending approval
    ↓ If allowed
CodeGenerator.generate(intent, context, tools) → executable code
    ↓
Sandbox.execute(code) → result
    ↓
Construct and return AgentResponse
```

---

## Directory Structure

```
agenticapi/
├── CLAUDE.md                        ← This file
├── pyproject.toml
├── LICENSE
├── README.md
├── CONTRIBUTING.md
├── SECURITY.md
├── src/
│   └── agenticapi/
│       ├── __init__.py              # Version, public API re-export
│       ├── app.py                   # AgenticApp (equivalent to FastAPI's FastAPI class)
│       ├── routing.py               # AgentRouter (equivalent to FastAPI's APIRouter)
│       ├── params.py                # Parameter definitions such as HarnessDepends
│       ├── types.py                 # Common type definitions
│       ├── exceptions.py            # Exception hierarchy
│       ├── _compat.py               # Python/dependency version compatibility
│       ├── interface/
│       │   ├── __init__.py
│       │   ├── endpoint.py          # AgentEndpoint, AgentEndpointHandler
│       │   ├── intent.py            # Intent, IntentParser, IntentScope
│       │   ├── session.py           # SessionManager, Session
│       │   ├── response.py          # AgentResponse, ResponseFormatter
│       │   ├── compat/
│       │   │   ├── __init__.py
│       │   │   ├── rest.py          # REST compatibility (expose_as_rest)
│       │   │   ├── graphql.py       # GraphQL compatibility
│       │   │   └── fastapi.py       # FastAPI mount (mount_fastapi)
│       │   └── a2a/
│       │       ├── __init__.py
│       │       ├── protocol.py      # A2A message type definitions
│       │       ├── server.py        # A2AServer
│       │       ├── client.py        # A2AClient
│       │       ├── capability.py    # Capability, CapabilityNegotiator
│       │       ├── trust.py         # TrustPolicy, TrustScoring
│       │       └── discovery.py     # ServiceDiscovery
│       ├── harness/
│       │   ├── __init__.py
│       │   ├── engine.py            # HarnessEngine
│       │   ├── policy/
│       │   │   ├── __init__.py
│       │   │   ├── base.py          # Policy base class
│       │   │   ├── code_policy.py   # CodePolicy
│       │   │   ├── data_policy.py   # DataPolicy
│       │   │   ├── resource_policy.py
│       │   │   ├── runtime_policy.py
│       │   │   └── evaluator.py     # PolicyEvaluator
│       │   ├── sandbox/
│       │   │   ├── __init__.py
│       │   │   ├── base.py          # SandboxRuntime base class
│       │   │   ├── process.py       # ProcessSandbox
│       │   │   ├── container.py     # ContainerSandbox
│       │   │   ├── static_analysis.py
│       │   │   ├── monitors.py
│       │   │   └── validators.py
│       │   ├── approval/
│       │   │   ├── __init__.py
│       │   │   ├── workflow.py      # ApprovalWorkflow
│       │   │   ├── rules.py         # ApprovalRule
│       │   │   └── notifiers.py     # Slack, Email notifications
│       │   └── audit/
│       │       ├── __init__.py
│       │       ├── recorder.py      # AuditRecorder
│       │       ├── trace.py         # ExecutionTrace
│       │       └── exporters.py     # OpenTelemetry exporter
│       ├── runtime/
│       │   ├── __init__.py
│       │   ├── code_generator.py    # CodeGenerator
│       │   ├── context.py           # ContextManager, ContextWindow
│       │   ├── prompts/             # LLM prompt templates
│       │   │   ├── __init__.py
│       │   │   ├── code_generation.py  # Code generation prompts
│       │   │   └── intent_parsing.py   # Intent parsing prompts
│       │   ├── tools/
│       │   │   ├── __init__.py
│       │   │   ├── registry.py      # ToolRegistry
│       │   │   ├── base.py          # Tool base class
│       │   │   ├── database.py      # DatabaseTool
│       │   │   ├── http_client.py   # HttpClientTool
│       │   │   ├── cache.py         # CacheTool
│       │   │   └── queue.py         # QueueTool
│       │   └── llm/
│       │       ├── __init__.py
│       │       ├── base.py          # LLMBackend Protocol
│       │       ├── anthropic.py     # AnthropicBackend
│       │       ├── openai.py        # OpenAIBackend
│       │       └── mock.py          # MockBackend (for testing)
│       ├── application/
│       │   ├── __init__.py
│       │   ├── pipeline.py          # DynamicPipeline, PipelineStage
│       │   ├── data_access.py       # AdaptiveDataAccess, DataSource
│       │   ├── business_rules.py    # BusinessRuleEngine, NaturalLanguageRule
│       │   └── cross_domain.py      # CrossDomainOptimizer
│       ├── ops/
│       │   ├── __init__.py
│       │   ├── base.py              # OpsAgent base class
│       │   ├── log_analyst.py       # LogAnalyst
│       │   ├── auto_healer.py       # AutoHealer
│       │   ├── perf_tuner.py        # PerformanceTuner
│       │   ├── incident.py          # IncidentResponder
│       │   └── knowledge_base.py    # KnowledgeBase
│       ├── testing/
│       │   ├── __init__.py
│       │   ├── agent_test_case.py   # AgentTestCase
│       │   ├── mocks.py            # mock_llm, MockA2AService
│       │   ├── assertions.py       # assert_code_safe, assert_policy_enforced
│       │   ├── fixtures.py         # pytest fixtures
│       │   └── benchmark.py        # BenchmarkRunner
│       └── cli/
│           ├── __init__.py
│           ├── main.py             # CLI entry point (click/typer)
│           ├── dev.py              # `agenticapi dev`
│           ├── console.py          # `agenticapi console`
│           └── ops.py              # `agenticapi ops`
├── tests/
│   ├── conftest.py                 # Shared fixtures
│   ├── unit/
│   │   ├── test_app.py
│   │   ├── test_intent.py
│   │   ├── test_session.py
│   │   ├── test_response.py
│   │   ├── harness/
│   │   │   ├── test_policy_evaluator.py
│   │   │   ├── test_code_policy.py
│   │   │   ├── test_data_policy.py
│   │   │   ├── test_sandbox.py
│   │   │   ├── test_static_analysis.py
│   │   │   └── test_approval.py
│   │   ├── runtime/
│   │   │   ├── test_code_generator.py
│   │   │   ├── test_context.py
│   │   │   ├── test_tool_registry.py
│   │   │   └── test_llm_backend.py
│   │   ├── application/
│   │   │   ├── test_pipeline.py
│   │   │   ├── test_data_access.py
│   │   │   └── test_business_rules.py
│   │   ├── ops/
│   │   │   ├── test_log_analyst.py
│   │   │   ├── test_auto_healer.py
│   │   │   └── test_incident.py
│   │   └── a2a/
│   │       ├── test_protocol.py
│   │       ├── test_capability.py
│   │       └── test_trust.py
│   ├── integration/
│   │   ├── test_endpoint_flow.py
│   │   ├── test_harness_flow.py
│   │   ├── test_a2a_flow.py
│   │   └── test_fastapi_compat.py
│   ├── e2e/
│   │   └── test_full_request_cycle.py
│   └── benchmarks/
│       ├── bench_intent_parsing.py
│       ├── bench_policy_evaluation.py
│       ├── bench_sandbox_startup.py
│       └── bench_static_analysis.py
└── examples/
    ├── 01_hello_agent/
    │   └── app.py
    ├── 02_ecommerce/
    │   ├── app.py
    │   ├── agents/
    │   └── harness/
    └── 03_a2a_microservices/
        ├── service_a/
        └── service_b/
```

---

## Coding Conventions

### Python General

- **Target Python 3.13+**. Actively use `match` statements, `type` statements, and the new `TypeVar` syntax.
- **All public APIs (functions, classes, methods) must have type hints.** Internal implementations should also have type hints wherever possible.
- **Docstrings use Google style**. Public APIs must always have docstrings.
- **Formatter is `ruff format`**, **linter is `ruff check`**. Configuration is in `pyproject.toml`.
- **Type checking uses `mypy`** (`strict` mode).
- **Line length is 99 characters**.
- **Import order**: stdlib → third-party → agenticapi (managed automatically by ruff).

### Naming Conventions

```python
# Modules: snake_case
code_generator.py
static_analysis.py

# Classes: PascalCase
class AgenticApp: ...
class IntentParser: ...
class CodePolicy: ...

# Functions/methods: snake_case
async def parse_intent(raw: str) -> Intent: ...
def evaluate_policy(intent: Intent) -> PolicyResult: ...

# Constants: UPPER_SNAKE_CASE
DEFAULT_MAX_TOKENS = 4096
SANDBOX_TIMEOUT_SECONDS = 60

# Private: _prefix
class AgenticApp:
    def _setup_routes(self) -> None: ...
    _starlette_app: Starlette

# Do not use dunder names (except Python standard ones like __init__, __call__)
```

### async/await Principles

AgenticAPI is an **async-first framework**.

```python
# ✅ Correct: Use async def as the default
async def parse_intent(raw: str) -> Intent: ...

# ✅ Correct: If a sync version is needed, provide it separately with _sync suffix
def parse_intent_sync(raw: str) -> Intent:
    return asyncio.run(parse_intent(raw))

# ❌ Wrong: Do not use sync def as the default
def parse_intent(raw: str) -> Intent: ...  # NO

# ✅ Correct: Pure computations without I/O can use sync def
def calculate_trust_score(factors: list[TrustFactor]) -> float: ...

# ✅ Correct: Context managers should also be async
async with Sandbox() as sandbox:
    result = await sandbox.execute(code)

# ✅ Correct: Iterators should also be async
async for event in audit_stream:
    process(event)
```

### Pydantic Model Conventions

```python
from pydantic import BaseModel, Field

# ✅ Configuration/input schemas → BaseModel
class CodePolicy(BaseModel):
    """Code generation policy. Defines constraints on code an agent can generate."""
    allowed_modules: list[str] = Field(
        default_factory=list,
        description="Allowed Python modules",
    )
    denied_modules: list[str] = Field(
        default_factory=list,
        description="Denied Python modules",
    )
    max_code_lines: int = Field(default=500, ge=1, description="Maximum lines of generated code")

    model_config = {"extra": "forbid"}  # Reject unknown fields

# ✅ Internal data / immutable objects → dataclass (frozen)
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Intent:
    """Parsed intent. Immutable object."""
    raw: str
    action: str
    parameters: dict[str, Any]
    confidence: float

# ✅ Events/records → dataclass
@dataclass(slots=True)
class AuditRecord:
    trace_id: str
    timestamp: datetime
    # ...
```

**Guidelines for choosing between types:**

| Use Case | Type | Reason |
|---|---|---|
| User input configuration/schema | `pydantic.BaseModel` | Validation, JSON conversion, schema generation |
| Internal immutable data | `@dataclass(frozen=True, slots=True)` | Lightweight, hashable |
| Internal mutable data | `@dataclass(slots=True)` | Lightweight |
| Enumerations | `enum.StrEnum` | String-comparable |
| Type aliases | `type` statement | Python 3.13+ |

### Exception Design

```python
# src/agenticapi/exceptions.py

class AgenticAPIError(Exception):
    """Base class for all AgenticAPI exceptions."""

# --- Harness-related ---
class HarnessError(AgenticAPIError):
    """Base exception for harness engine."""

class PolicyViolation(HarnessError):
    """Policy violation. Generated code does not conform to policy."""
    def __init__(self, policy: str, violation: str, generated_code: str | None = None):
        self.policy = policy
        self.violation = violation
        self.generated_code = generated_code
        super().__init__(f"Policy '{policy}' violated: {violation}")

class SandboxViolation(HarnessError):
    """Sandbox violation. A prohibited operation was detected at runtime."""

class ApprovalRequired(HarnessError):
    """Approval required. Human approval is needed to proceed."""

class ApprovalDenied(HarnessError):
    """Approval was denied."""

class ApprovalTimeout(HarnessError):
    """Approval timed out."""

# --- Runtime-related ---
class AgentRuntimeError(AgenticAPIError):
    """Base exception for agent runtime."""

class CodeGenerationError(AgentRuntimeError):
    """Code generation failed."""

class CodeExecutionError(AgentRuntimeError):
    """Execution of generated code failed."""

class ToolError(AgentRuntimeError):
    """Tool invocation failed."""

class ContextError(AgentRuntimeError):
    """Context construction failed."""

# --- Interface-related ---
class InterfaceError(AgenticAPIError):
    """Base exception for the interface layer."""

class IntentParseError(InterfaceError):
    """Intent parsing failed."""

class SessionError(InterfaceError):
    """Session management error."""

class A2AError(InterfaceError):
    """Agent-to-Agent communication error."""
```

**Exception usage principles:**
- **Errors shown to users** → `InterfaceError` family. Mapped to HTTP responses.
- **Internal control flow** → `HarnessError` family. Detected and handled by the harness.
- **Unexpected errors** → `AgentRuntimeError` family. Logged and routed to incident response.
- **Never swallow exceptions.** `except Exception: pass` is prohibited.

### Error to HTTP Response Mapping

```python
EXCEPTION_STATUS_MAP: dict[type[AgenticAPIError], int] = {
    IntentParseError: 400,       # Bad Request
    PolicyViolation: 403,        # Forbidden
    ApprovalRequired: 202,       # Accepted (async approval pending)
    ApprovalDenied: 403,         # Forbidden
    ApprovalTimeout: 408,        # Request Timeout
    SandboxViolation: 403,       # Forbidden
    CodeGenerationError: 500,    # Internal Server Error
    CodeExecutionError: 500,     # Internal Server Error
    ToolError: 502,              # Bad Gateway (external tool failure)
    SessionError: 400,           # Bad Request
    A2AError: 502,               # Bad Gateway
}
```

### Logging

```python
import structlog

logger = structlog.get_logger(__name__)

# ✅ Use structured logging
logger.info("intent_parsed", intent_action=intent.action, confidence=intent.confidence)
logger.warning("policy_near_limit", policy="resource", cpu_usage=0.78, threshold=0.80)
logger.error(
    "code_execution_failed",
    error=str(e),
    generated_code=code[:200],
    trace_id=ctx.trace_id,
)

# ❌ Do not use string formatting
logger.info(f"Intent parsed: {intent.action}")  # NO
```

---

## Testing Conventions

### Writing Tests

```python
import pytest
from agenticapi.testing import mock_llm, create_test_app

# ✅ Test function naming: test_{subject}_{condition}_{expected_result}
async def test_intent_parser_with_simple_query_returns_read_action():
    parser = IntentParser()
    intent = await parser.parse("Tell me the number of orders this month")
    assert intent.action == "read"
    assert intent.confidence > 0.8

# ✅ Use fixtures
@pytest.fixture
def app():
    """AgenticApp for testing."""
    return create_test_app(
        policies=[CodePolicy(denied_modules=["os"])],
    )

@pytest.fixture
def mock_anthropic():
    """Mock LLM calls."""
    with mock_llm(responses=["SELECT COUNT(*) FROM orders"]) as m:
        yield m

# ✅ Use parametrize
@pytest.mark.parametrize("raw_intent,expected_action", [
    ("Tell me the order count", "read"),
    ("Cancel the order", "write"),
    ("Analyze order trends", "analyze"),
])
async def test_intent_parser_action_classification(raw_intent, expected_action):
    parser = IntentParser()
    intent = await parser.parse(raw_intent)
    assert intent.action == expected_action
```

### Test Categories and Markers

```python
# pyproject.toml
# [tool.pytest.ini_options]
# markers = [
#     "requires_llm: Tests requiring an LLM API key",
#     "requires_db: Tests requiring a database connection",
#     "requires_redis: Tests requiring a Redis connection",
#     "slow: Tests taking more than 10 seconds",
#     "benchmark: Benchmark tests",
# ]
# asyncio_mode = "auto"
```

### Mocking Strategy

```python
from agenticapi.testing import mock_llm, MockA2AService, MockSandbox

# LLM mock: Directly specify the generated code
with mock_llm(responses=["SELECT COUNT(*) FROM orders WHERE created_at > '2024-01-01'"]):
    result = await agent.process(intent)

# LLM mock: Multi-turn responses
with mock_llm(responses=[
    "SELECT * FROM products",                                          # 1st call
    "UPDATE products SET price = price * 0.9 WHERE category = 'sale'", # 2nd call
]):
    result = await agent.process(multi_step_intent)

# A2A mock
async with MockA2AService("logistics") as mock:
    mock.register_capability("estimate_delivery", handler=lambda req: {"days": 2})
    result = await a2a_client.request("estimate_delivery", {"destination": "Tokyo"})

# Sandbox mock (for unit tests)
sandbox = MockSandbox(
    allowed_results={"SELECT COUNT(*)": [{"count": 42}]},
    denied_operations=["DROP TABLE"],
)
```

### Patterns for Verifying Agent Behavior in Tests

```python
# Pattern 1: Verify safety of generated code
async def test_generated_code_safety(app):
    with mock_llm(responses=["import os; os.system('rm -rf /')"]):
        with pytest.raises(PolicyViolation, match="denied_modules"):
            await app.process_intent("Test")

# Pattern 2: Verify harness policy compliance
async def test_data_policy_restricts_columns(app):
    with mock_llm(responses=["SELECT password_hash FROM users"]):
        with pytest.raises(PolicyViolation, match="restricted_columns"):
            await app.process_intent("Get user info")

# Pattern 3: Verify audit record creation
async def test_audit_record_created(app, audit_recorder):
    with mock_llm(responses=["SELECT 1"]):
        await app.process_intent("Test")
    records = audit_recorder.get_records()
    assert len(records) == 1
    assert records[0].generated_code == "SELECT 1"
    assert records[0].policy_evaluations is not None

# Pattern 4: Verify approval workflow triggering
async def test_approval_triggered_for_bulk_write(app):
    with mock_llm(responses=["DELETE FROM orders WHERE status = 'cancelled'"]):
        response = await app.process_intent("Delete all cancelled orders")
    assert response.status == "pending_approval"
    assert response.approval_request.approvers == ["db_admin"]
```

---

## Implementation Guide and Skeleton Code for Key Components

### AgenticApp — Main Application Class

Equivalent to FastAPI's `FastAPI` class. Holds Starlette/ASGI internally and integrates agent endpoints with the harness.

```python
# Skeleton of src/agenticapi/app.py

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from agenticapi.harness.engine import HarnessEngine
    from agenticapi.interface.endpoint import AgentEndpointDef
    from agenticapi.ops.base import OpsAgent
    from agenticapi.runtime.llm.base import LLMBackend

class AgenticApp:
    """Main AgenticAPI application.

    Works as an ASGI application like FastAPI.
    Can be started directly with uvicorn:
        uvicorn myapp:app --host 0.0.0.0 --port 8000

    Example:
        app = AgenticApp(title="My Service")

        @app.agent_endpoint(name="orders", autonomy_level="supervised")
        async def order_agent(intent, context):
            pass
    """

    def __init__(
        self,
        *,
        title: str = "AgenticAPI",
        version: str = "0.1.0",
        harness: HarnessEngine | None = None,
        llm: LLMBackend | None = None,
    ) -> None:
        self.title = title
        self.version = version
        self._endpoints: dict[str, AgentEndpointDef] = {}
        self._harness = harness  # lazy-init if None
        self._llm = llm
        self._ops_agents: list[OpsAgent] = []
        self._starlette_app: Starlette | None = None

    def agent_endpoint(
        self,
        name: str,
        *,
        description: str = "",
        intent_scope: Any | None = None,
        autonomy_level: str = "supervised",
        policies: list[Any] | None = None,
        approval: Any | None = None,
        sandbox: Any | None = None,
    ) -> Callable:
        """Decorator to register an agent endpoint."""
        def decorator(func: Callable) -> Callable:
            self._endpoints[name] = AgentEndpointDef(
                name=name,
                description=description,
                handler=func,
                intent_scope=intent_scope,
                autonomy_level=autonomy_level,
                policies=policies or [],
                approval=approval,
                sandbox=sandbox,
            )
            # Defer Starlette rebuild
            self._starlette_app = None
            return func
        return decorator

    def include_router(self, router: Any, *, prefix: str = "") -> None:
        """Integrate an AgentRouter. Equivalent to FastAPI's include_router."""
        for name, endpoint_def in router.endpoints.items():
            full_name = f"{prefix}.{name}" if prefix else name
            self._endpoints[full_name] = endpoint_def
        self._starlette_app = None

    def register_ops_agent(self, agent: OpsAgent) -> None:
        """Register an ops agent."""
        self._ops_agents.append(agent)

    def _build_starlette(self) -> Starlette:
        """Build the internal Starlette app."""
        routes: list[Route] = []
        for name, endpoint_def in self._endpoints.items():
            handler = self._create_endpoint_handler(endpoint_def)
            routes.append(Route(f"/agent/{name}", handler, methods=["POST"]))
        routes.append(Route("/health", self._health_handler, methods=["GET"]))
        return Starlette(routes=routes, on_startup=[self._on_startup])

    def _create_endpoint_handler(self, endpoint_def: AgentEndpointDef) -> Callable:
        """Generate a Starlette handler function from an AgentEndpointDef."""
        async def handler(request: Request) -> JSONResponse:
            # Implement the full pipeline here:
            # Intent parsing → Harness → CodeGen → Sandbox → Response
            ...
        return handler

    async def _health_handler(self, request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": self.version})

    async def _on_startup(self) -> None:
        """Startup initialization. Starts OpsAgents, etc."""
        for agent in self._ops_agents:
            await agent.start()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """ASGI interface."""
        if self._starlette_app is None:
            self._starlette_app = self._build_starlette()
        await self._starlette_app(scope, receive, send)
```

### Intent — Intent Model

```python
# src/agenticapi/interface/intent.py

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IntentAction(StrEnum):
    """Intent action types."""
    READ = "read"
    WRITE = "write"
    ANALYZE = "analyze"
    EXECUTE = "execute"
    CLARIFY = "clarify"


@dataclass(frozen=True, slots=True)
class Intent:
    """Parsed intent. An immutable object that serves as the starting point for agent processing.

    Attributes:
        raw: The original natural language request
        action: The classified action type
        domain: Domain ("order", "product", etc.)
        parameters: Extracted parameters
        confidence: Parse confidence (0.0-1.0)
        ambiguities: List of detected ambiguities
        session_context: Accumulated session context
    """
    raw: str
    action: IntentAction
    domain: str
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    ambiguities: list[str] = field(default_factory=list)
    session_context: dict[str, Any] = field(default_factory=dict)

    @property
    def is_write(self) -> bool:
        """Determine if this is a write operation."""
        return self.action in (IntentAction.WRITE, IntentAction.EXECUTE)

    @property
    def needs_clarification(self) -> bool:
        """Determine if ambiguity resolution is needed."""
        return self.action == IntentAction.CLARIFY or len(self.ambiguities) > 0
```

### HarnessEngine — Harness Engine

```python
# src/agenticapi/harness/engine.py

class HarnessEngine:
    """Harness engine that controls agent behavior.

    All agent operations pass through the HarnessEngine.
    Processes in the order: policy evaluation → sandbox execution → audit recording.

    Processing flow:
        1. Policy evaluation (including static analysis)
        2. Approval check (if required)
        3. Code execution in sandbox
        4. Post-execution verification
        5. Audit record recording
    """

    async def execute(
        self,
        *,
        intent: Intent,
        generated_code: str,
        endpoint_policies: list[Policy],
        approval_config: ApprovalConfig | None,
        tools: ToolRegistry,
        context: AgentContext,
    ) -> ExecutionResult:
        """Execute code with harness controls.

        Raises:
            PolicyViolation: Policy violation
            ApprovalRequired: Approval is required
            SandboxViolation: Runtime security violation
        """
        # 1. Policy evaluation
        # 2. Approval check
        # 3. Sandbox execution
        # 4. Post-execution verification
        # 5. Audit recording
        ...
```

### CodeGenerator — Code Generation Engine

```python
# src/agenticapi/runtime/code_generator.py

class CodeGenerator:
    """Engine that generates Python code from intents.

    Uses an LLM backend to generate Python code from Intent and Context.
    Generated code is verified by the HarnessEngine before being executed in the Sandbox.

    Code generation pipeline:
        1. Intent Decomposition
        2. Context Assembly
        3. Code Planning
        4. Code Generation (by LLM)
        5. Code Extraction (extraction and parsing)
    """

    async def generate(self, intent: Intent, context: AgentContext) -> GeneratedCode:
        """Generate code from an intent.

        Raises:
            CodeGenerationError: Code generation failed
        """
        ...
```

### LLMBackend — LLM Backend Abstraction

```python
# src/agenticapi/runtime/llm/base.py

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A message to send to the LLM."""
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True, slots=True)
class LLMPrompt:
    """A prompt to the LLM."""
    system: str
    messages: list[LLMMessage]
    tools: list[dict[str, Any]] | None = None
    max_tokens: int = 4096
    temperature: float = 0.1


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """LLM token usage."""
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """LLM response."""
    content: str
    reasoning: str | None = None
    confidence: float = 1.0
    usage: LLMUsage = field(default_factory=lambda: LLMUsage(0, 0))
    model: str = ""


@dataclass(frozen=True, slots=True)
class LLMChunk:
    """A chunk from a streaming response."""
    content: str
    is_final: bool = False


class LLMBackend(Protocol):
    """Protocol definition for LLM backends.

    By using Protocol (structural subtyping), implementations can
    provide backends without depending on AgenticAPI.
    """

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        """Send a prompt and receive a response."""
        ...

    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
        """Receive a streaming response."""
        ...

    @property
    def model_name(self) -> str:
        """The name of the model in use."""
        ...
```

### SandboxRuntime — Sandbox Base

```python
# src/agenticapi/harness/sandbox/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Sandbox resource limits."""
    max_cpu_seconds: float = 30.0
    max_memory_mb: int = 512
    max_execution_time_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class ResourceMetrics:
    """Runtime resource usage metrics."""
    cpu_time_ms: float
    memory_peak_mb: float
    wall_time_ms: float


@dataclass(slots=True)
class SandboxResult:
    """Sandbox execution result."""
    output: Any
    return_value: Any
    metrics: ResourceMetrics
    stdout: str = ""
    stderr: str = ""


class SandboxRuntime(ABC):
    """Base class for sandbox execution environments.

    Executes generated code in an isolated environment.
    Provides two implementations: ProcessSandbox (process isolation)
    and ContainerSandbox (container isolation).

    Only ProcessSandbox is implemented in Phase 1.
    """

    @abstractmethod
    async def execute(
        self,
        code: str,
        tools: Any,  # ToolRegistry
        resource_limits: ResourceLimits,
    ) -> SandboxResult:
        """Execute code inside the sandbox.

        Raises:
            SandboxViolation: Security violation detected
            CodeExecutionError: Code execution failed
        """
        ...

    @abstractmethod
    async def __aenter__(self) -> SandboxRuntime:
        ...

    @abstractmethod
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        ...
```

### StaticAnalysis — Static Analysis

```python
# src/agenticapi/harness/sandbox/static_analysis.py

"""AST-based safety check for generated code.

Analyzes Python code generated by agents at the AST level before execution
to detect dangerous patterns.

Detected dangerous patterns:
    - Import of denied modules (os, subprocess, sys, etc.)
    - Use of eval / exec
    - Direct calls to __import__
    - Filesystem access (open, pathlib, etc.)
    - Network access (socket, urllib, etc.)
    - Dynamic attribute access (getattr with computed name)
    - Modification of global variables
    - Structures with potential infinite loops

Note:
    AST analysis is limited to detecting known patterns.
    It cannot handle advanced obfuscation, so safety is ensured
    through defense-in-depth with the sandbox.
"""

import ast
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SafetyViolation:
    """A safety violation detected by static analysis."""
    rule: str
    description: str
    line: int
    col: int
    severity: str  # "error" | "warning"


@dataclass(frozen=True, slots=True)
class SafetyResult:
    """Result of static analysis."""
    safe: bool
    violations: list[SafetyViolation] = field(default_factory=list)


def check_code_safety(
    code: str,
    *,
    allowed_modules: list[str] | None = None,
    denied_modules: list[str] | None = None,
    deny_eval_exec: bool = True,
    deny_dynamic_import: bool = True,
) -> SafetyResult:
    """Check the safety of generated code via AST analysis.

    Args:
        code: The Python code to analyze
        allowed_modules: List of allowed modules (whitelist mode when specified)
        denied_modules: List of denied modules (blacklist mode when specified)
        deny_eval_exec: Whether to deny eval/exec
        deny_dynamic_import: Whether to deny __import__

    Returns:
        SafetyResult: The analysis result
    """
    ...
```

---

## Implementation Priority (Phase 1)

Items to implement in Phase 1 (v0.1). **Implement in this order.** Write tests before code at each step (TDD).

### Step 1: Project Foundation
1. `pyproject.toml` — Dependencies, build config, ruff/mypy/pytest settings
2. `src/agenticapi/__init__.py` — Version, public API
3. `src/agenticapi/types.py` — Common types
4. `src/agenticapi/exceptions.py` — Exception hierarchy
5. `tests/conftest.py` — Shared fixtures

### Step 2: Runtime Foundation (implement from the dependency-free layer)
6. `src/agenticapi/runtime/llm/base.py` — LLMBackend Protocol, data classes
7. `src/agenticapi/runtime/llm/mock.py` — MockBackend (for testing)
8. `src/agenticapi/runtime/llm/anthropic.py` — AnthropicBackend
9. `src/agenticapi/runtime/tools/base.py` — Tool base Protocol
10. `src/agenticapi/runtime/tools/registry.py` — ToolRegistry
11. `src/agenticapi/runtime/tools/database.py` — DatabaseTool
12. `src/agenticapi/runtime/context.py` — ContextManager
13. `src/agenticapi/runtime/prompts/code_generation.py` — Code generation prompts
14. `src/agenticapi/runtime/prompts/intent_parsing.py` — Intent parsing prompts
15. `src/agenticapi/runtime/code_generator.py` — CodeGenerator

### Step 3: Harness Foundation
16. `src/agenticapi/harness/policy/base.py` — Policy base
17. `src/agenticapi/harness/policy/code_policy.py` — CodePolicy
18. `src/agenticapi/harness/policy/data_policy.py` — DataPolicy
19. `src/agenticapi/harness/policy/resource_policy.py` — ResourcePolicy
20. `src/agenticapi/harness/policy/evaluator.py` — PolicyEvaluator
21. `src/agenticapi/harness/sandbox/base.py` — SandboxRuntime ABC
22. `src/agenticapi/harness/sandbox/static_analysis.py` — AST static analysis
23. `src/agenticapi/harness/sandbox/process.py` — ProcessSandbox
24. `src/agenticapi/harness/audit/trace.py` — ExecutionTrace
25. `src/agenticapi/harness/audit/recorder.py` — AuditRecorder
26. `src/agenticapi/harness/engine.py` — HarnessEngine

### Step 4: Interface
27. `src/agenticapi/interface/intent.py` — Intent, IntentParser
28. `src/agenticapi/interface/response.py` — AgentResponse, ResponseFormatter
29. `src/agenticapi/interface/session.py` — SessionManager
30. `src/agenticapi/interface/endpoint.py` — AgentEndpoint, AgentEndpointDef
31. `src/agenticapi/routing.py` — AgentRouter
32. `src/agenticapi/app.py` — AgenticApp

### Step 5: Testing Framework & CLI
33. `src/agenticapi/testing/mocks.py` — mock_llm, MockSandbox
34. `src/agenticapi/testing/assertions.py` — assert_code_safe, etc.
35. `src/agenticapi/testing/agent_test_case.py` — AgentTestCase
36. `src/agenticapi/testing/fixtures.py` — pytest fixtures (create_test_app, etc.)
37. `src/agenticapi/cli/main.py` — CLI entry point
38. `src/agenticapi/cli/dev.py` — Development server (`agenticapi dev`)

### Step 6: REST Compatibility & Examples
39. `src/agenticapi/interface/compat/fastapi.py` — FastAPI mount
40. `src/agenticapi/interface/compat/rest.py` — REST compatibility
41. `examples/01_hello_agent/app.py` — Minimal working example

---

## Design Decision Records

Refer to the following design decisions during development.

### Why Build on Starlette

- FastAPI is built on Starlette. By following the same pattern, AgenticAPI can maintain compatibility with FastAPI.
- Since it operates as an ASGI application, it can be started with existing ASGI servers such as uvicorn, Daphne, Hypercorn, etc.
- HTTP foundation features like middleware, routing, and WebSocket are delegated to Starlette, allowing AgenticAPI to focus on agent-specific logic.

### Why Distinguish Between Pydantic and dataclass

- Pydantic: Used at boundary surfaces that accept user input (configuration, API schemas). Where validation, JSON Schema generation, and environment variable loading are needed.
- dataclass: Used for internal data representation. Lighter than Pydantic, with `frozen=True` for immutability guarantees and `slots=True` for memory efficiency.

### Why Use Protocol

- By using `Protocol` (structural subtyping) instead of ABC, implementations can provide backends without depending on AgenticAPI.
- Third-party LLM wrapper libraries can be integrated into AgenticAPI without modification.
- Protocol is used for pluggable components like LLMBackend, Tool, etc.
- ABC is used for internal inheritance hierarchies (SandboxRuntime, OpsAgent, etc.).

### Why Implement the Sandbox in Two Phases

- For the Phase 1 MVP, `ProcessSandbox` (`subprocess` + `resource` module + AST analysis) provides sufficient safety. Easy to set up in development environments.
- For production and multi-tenant environments, switch to `ContainerSandbox` (nsjail / bubblewrap).
- By unifying both under the `SandboxRuntime` ABC, switching requires only a configuration change.

### Why Build Approval Workflows into the Framework

- Since agents autonomously generate and execute code, "human approval" is the last line of defense for safety.
- Leaving approval to application code risks implementation gaps. By building it into the framework, approval rules can be defined declaratively and made impossible to bypass.

---

## Performance Benchmarks

Even the Phase 1 MVP must meet the following benchmarks.

| Item | Target | Measurement |
|---|---|---|
| IntentParser.parse() | < 50ms (excluding LLM) | `tests/benchmarks/bench_intent_parsing.py` |
| PolicyEvaluator.evaluate() | < 10ms | `tests/benchmarks/bench_policy_evaluation.py` |
| Static analysis (AST check) | < 50ms / 1000 lines | `tests/benchmarks/bench_static_analysis.py` |
| ProcessSandbox startup | < 100ms | `tests/benchmarks/bench_sandbox_startup.py` |
| AgenticApp → Response (excluding LLM) | < 200ms overhead | `tests/benchmarks/bench_full_cycle.py` |

Benchmarks are automatically run in CI to detect regressions.

---

## Security Considerations

### Prompt Injection Countermeasures

User natural language requests are injected into LLM prompts. Implement the following defense-in-depth measures.

1. **Input sanitization**: Clearly separate user input from system prompts using XML tags, etc.
2. **Output verification**: Always run static analysis on LLM output (generated code). Even if prompt injection causes the LLM to generate dangerous code, it is blocked by the policy evaluator and sandbox.
3. **Defense in depth**: Defend across 4 layers: prompt design → static analysis → policy evaluation → sandbox. Even if one layer is breached, the remaining layers block the threat.
4. **Least privilege**: Set tool permissions to the minimum. For example, pass read-only DB connections to DatabaseTool.

### Sandbox Safety

Be aware of the limitations of ProcessSandbox (Phase 1).

- Process isolation via `multiprocessing` is not kernel-level isolation
- Resource limits via the `resource` module only work on Linux
- AST analysis can only detect known patterns (dynamic construction of `__import__` etc. may slip through)
- Phase 1 **assumes a trusted LLM backend (Claude)** and handles cases of extremely malicious LLM output only to a limited extent
- Migration to `ContainerSandbox` (implemented in Phase 2) is recommended for production environments

### Secret Management

- Read API keys from environment variables. Never hardcode them.
- When recording full LLM prompts in audit logs, incorporate a mechanism to mask users' personal information.
- Include `.env.test` for testing in `.gitignore`.

---

## Common Patterns and Implementation Notes

### Pattern: Endpoint Registration via Decorator

Follows FastAPI's `@app.get()` pattern. In the decorator implementation, return the function as-is and register it in the internal `_endpoints` dictionary. Refer to FastAPI's `add_api_route` pattern.

```python
# FastAPI
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    return {"user_id": user_id}

# AgenticAPI — Same pattern
@app.agent_endpoint(name="user_management")
async def user_agent(intent: Intent, context: AgentContext) -> AgentResponse:
    ...
```

### Pattern: Dependency Injection

Provide `HarnessDepends` modeled after FastAPI's `Depends`.

```python
@app.agent_endpoint(name="users")
async def user_agent(
    intent: Intent,
    context: AgentContext,
    harness: HarnessEngine = HarnessDepends(get_harness),
):
    ...
```

### Note: LLM Prompt Management

The prompts that `CodeGenerator` sends to the LLM are the most critical part determining framework quality. Prompts are managed as independent Python modules in the `src/agenticapi/runtime/prompts/` directory. Define them as functions (not hardcoded strings) to make them testable.

```python
# src/agenticapi/runtime/prompts/code_generation.py

def build_code_generation_prompt(
    intent: Intent,
    context: AssembledContext,
    tool_definitions: list[ToolDefinition],
) -> LLMPrompt:
    """Build an LLM prompt for code generation."""
    system = _build_system_prompt(tool_definitions)
    user = _build_user_prompt(intent, context)
    return LLMPrompt(system=system, messages=[LLMMessage("user", user)])
```

### Note: Preventing Circular Imports

Strictly manage inter-module dependencies. Use `TYPE_CHECKING` to avoid type-hint imports at runtime.

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agenticapi.harness.engine import HarnessEngine

class AgenticApp:
    def __init__(self, harness: HarnessEngine | None = None):
        ...
```

### Note: Test-First

Write tests before implementation for every module. Harness-related tests in particular are the last line of defense for security, so cover edge cases thoroughly.

```bash
# Implementation workflow
# 1. Write tests
# 2. Confirm tests fail (red)
# 3. Write minimal implementation to pass tests (green)
# 4. Refactor
# 5. Pass ruff format + ruff check + mypy
```

---

## Commit Message Conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/).

```
feat(interface): add IntentParser with LLM-based parsing
fix(harness): fix policy evaluation order for nested policies
docs(readme): add getting started section
test(sandbox): add benchmark for ProcessSandbox startup time
refactor(runtime): extract prompt building into separate module
chore(deps): update anthropic SDK to 0.40.0
perf(harness): cache AST analysis results for repeated code patterns
security(sandbox): add additional AST checks for __import__ patterns
```

Scopes are one of: `interface`, `harness`, `runtime`, `application`, `ops`, `cli`, `testing`, `deps`, `docs`.

---

## pyproject.toml Reference Configuration

```toml
[project]
name = "agenticapi"
version = "0.1.0"
description = "Agent-native web framework with harness engineering"
readme = "README.md"
license = {text = "Apache-2.0"}
requires-python = ">=3.13"
dependencies = [
    "starlette>=0.40.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.9.0",
    "structlog>=24.0.0",
    "httpx>=0.27.0",
    "anthropic>=0.40.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "pytest-benchmark>=4.0.0",
    "ruff>=0.7.0",
    "mypy>=1.12.0",
]

[project.scripts]
agenticapi = "agenticapi.cli.main:cli"

[tool.ruff]
line-length = 120
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "C4", "SIM", "TCH", "RUF"]

[tool.ruff.lint.isort]
known-first-party = ["agenticapi"]

[tool.mypy]
python_version = "3.13"
strict = true
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "requires_llm: Tests requiring an LLM API key",
    "requires_db: Tests requiring a database connection",
    "slow: Tests taking more than 10 seconds",
    "benchmark: Benchmark tests",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agenticapi"]
```
