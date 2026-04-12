# Testing Strategy and Conventions

---

## Test Directory Structure

```
tests/
    conftest.py              # Shared fixtures (e.g. mock backends, test apps)
    unit/                    # Fast, isolated tests (no network, no subprocess)
        test_app.py          # AgenticApp core behavior
        test_intent.py       # IntentParser, IntentScope
        test_security.py     # Auth schemes, Authenticator
        test_streaming.py    # AgentStream, events, transports
        test_typed_intents.py # Intent[T] generic injection
        test_openapi.py      # OpenAPI schema generation
        test_htmx.py         # HtmxHeaders, htmx_response_headers
        test_file_upload.py  # UploadedFiles injection
        test_custom_responses.py # HTMLResult, PlainTextResult, FileResult
        test_route_dependencies.py # Route-level Depends
        test_dx_integration.py # DI + response_model + @tool integration
        test_params.py       # Query/Header extraction
        test_compat.py       # REST/MCP compatibility
        harness/             # Policy, sandbox, audit, approval tests
        runtime/             # LLM backends, tools, memory, context
        dependencies/        # Scanner, solver tests
        observability/       # Tracing, metrics, propagation
        ops/                 # OpsAgent tests
        a2a/                 # Agent-to-agent protocol
        application/         # DynamicPipeline
    integration/             # Multi-component tests (may use subprocess)
    e2e/                     # Full HTTP request tests against example apps
        test_examples.py     # Exercises all 23 example apps
    benchmarks/              # Performance regression tests
```

---

## Running Tests

```bash
# All tests (unit + integration + e2e), excludes benchmarks
uv run pytest --ignore=tests/benchmarks -q

# Specific directory or file
uv run pytest tests/unit/harness/ -xvs
uv run pytest tests/unit/test_streaming.py -xvs

# With coverage
uv run pytest --cov=src/agenticapi

# Skip tests that require real LLM API keys
uv run pytest -m "not requires_llm"

# E2E only
uv run pytest tests/e2e/ -v

# Benchmarks only
uv run pytest tests/benchmarks/
```

---

## Writing Tests for New Features

### Unit test pattern

Every new module should have a corresponding test file. Place it in the matching subdirectory:

- `src/agenticapi/harness/policy/foo_policy.py` -> `tests/unit/harness/test_foo_policy.py`
- `src/agenticapi/runtime/tools/bar_tool.py` -> `tests/unit/runtime/test_bar_tool.py`

Standard structure:

```python
"""Tests for agenticapi.harness.policy.foo_policy."""
from __future__ import annotations
import pytest
from agenticapi.harness.policy.foo_policy import FooPolicy

class TestFooPolicy:
    def test_allows_clean_input(self) -> None:
        policy = FooPolicy()
        result = policy.evaluate(code="clean input", intent_action="read", intent_domain="data")
        assert result.allowed

    def test_denies_bad_input(self) -> None:
        policy = FooPolicy()
        result = policy.evaluate(code="bad input", intent_action="write", intent_domain="data")
        assert not result.allowed
        assert result.violations
```

### Using MockBackend

`MockBackend` (from `runtime/llm/mock.py`) is the standard way to test LLM-dependent code without network calls:

```python
from agenticapi.runtime.llm.mock import MockBackend

backend = MockBackend(
    default_response="result = 42",        # What generate() returns
    default_intent_action="read",          # What intent parsing returns
    default_intent_domain="data",
)
```

`MockBackend` implements the full `LLMBackend` protocol. Use it for:
- Testing `CodeGenerator` without a real LLM.
- Testing `IntentParser` with controlled classification.
- Testing harness pipeline end-to-end.

### Testing AgenticApp endpoints

Use Starlette's `TestClient` for synchronous HTTP testing:

```python
from starlette.testclient import TestClient
from agenticapi import AgenticApp

app = AgenticApp(title="test")

@app.agent_endpoint(name="greet")
async def greet(intent, context):
    return {"message": "hello"}

client = TestClient(app)
response = client.post("/agent/greet", json={"intent": "say hello"})
assert response.status_code == 200
data = response.json()
assert data["result"]["message"] == "hello"
```

---

## E2E Test Pattern (`test_examples.py`)

The e2e test suite exercises every example app with real HTTP requests. The pattern:

1. **`_load_app(module_path)`** — Imports the example module and returns its `app` object.
2. **`_post_intent(client, endpoint, intent)`** — POSTs an intent JSON body to `/agent/{endpoint}`, asserts status in `expected_statuses`, returns parsed JSON.
3. **`_assert_health_ok(client)`** — GETs `/health` and asserts `status == "ok"`.
4. **`_parse_sse_events(body)`** — Parses SSE frames from streaming responses.

Each example gets its own test class (e.g. `TestExample01HelloAgent`) with a `@pytest.fixture` that creates the `TestClient`:

```python
class TestExample01HelloAgent:
    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.01_hello_agent.app")
        return TestClient(app)

    def test_health(self, client: TestClient) -> None:
        _assert_health_ok(client)

    def test_greet(self, client: TestClient) -> None:
        data = _post_intent(client, "greet", "Hello world")
        assert data["status"] == "completed"
```

Tests are written to pass regardless of whether LLM API keys are set. When keys are absent, examples run in direct-handler mode.

### Adding e2e tests for a new example

1. Add a new test class in `tests/e2e/test_examples.py`.
2. Always test `/health` and at least one endpoint.
3. Use `expected_statuses={200, 202}` when the endpoint may trigger approval workflows.
4. For streaming endpoints, use `_parse_sse_events` to verify event structure.

---

## Performance Targets

These targets are regression thresholds. Benchmarks in `tests/benchmarks/` verify them.

| Component | Target |
|---|---|
| `IntentParser.parse()` (keyword mode) | < 50ms |
| `PolicyEvaluator.evaluate()` | < 15ms |
| Static analysis (`check_code_safety`, 1000 lines) | < 50ms |
| `ProcessSandbox` startup | < 100ms |

---

## Test-First Workflow

1. Write the test first (it should fail).
2. Implement the minimum code to make it pass.
3. Refactor.
4. Run the quality gates:

```bash
uv run ruff format src/ tests/ examples/
uv run ruff check src/ tests/ examples/
uv run mypy src/agenticapi/
uv run pytest --ignore=tests/benchmarks
```

All four must pass before a feature is considered complete.
