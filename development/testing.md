# Testing Guide

## Test Suite Overview

| Category | Files | Tests | Purpose |
|---|---|---|---|
| Unit tests | 45+ | ~540 | Individual module correctness |
| Integration tests | 3 | ~30 | Cross-module interaction |
| E2E tests | 2 | ~80 | Full HTTP request cycle + all 10 example apps |
| Benchmarks | 4 | 10 | Performance regression detection |
| **Total** | **55+** | **666** | **89% code coverage** |

## Running Tests

```bash
# All tests
uv run pytest

# Exclude benchmarks (faster)
uv run pytest --ignore=tests/benchmarks

# With coverage
uv run pytest --cov=src/agenticapi --cov-report=term-missing

# Specific module
uv run pytest tests/unit/harness/test_static_analysis.py -xvs

# Only benchmarks
uv run pytest tests/benchmarks/

# Only E2E (exercises all 9 examples)
uv run pytest tests/e2e/ -v

# Skip tests requiring LLM API keys
uv run pytest -m "not requires_llm"

# Using Makefile
make test           # All tests
make test-cov       # With coverage
make test-unit      # Unit only
make test-e2e       # E2E only
make test-benchmark # Benchmarks only
make ci             # Full CI: lint + typecheck + test
```

## Test Patterns

### AgentTestCase (base class)

```python
from agenticapi.testing import AgentTestCase
from agenticapi.harness.policy.code_policy import CodePolicy

class TestMyAgent(AgentTestCase):
    def setup_method(self):
        self.setup_app(
            policies=[CodePolicy(denied_modules=["os"])],
            llm_responses=["result = 42"],
        )

    async def test_process_intent(self):
        @self.app.agent_endpoint(name="test")
        async def handler(intent, context):
            return {"ok": True}

        response = await self.process_intent("show data")
        assert response.status == "completed"
```

### Mock LLM

```python
from agenticapi.testing import mock_llm

with mock_llm(responses=["SELECT COUNT(*) FROM orders"]) as backend:
    response = await backend.generate(prompt)
    assert response.content == "SELECT COUNT(*) FROM orders"
    assert backend.call_count == 1
    assert backend.prompts[0].system  # inspect sent prompts
```

### Mock Sandbox

```python
from agenticapi.testing import MockSandbox

sandbox = MockSandbox(
    allowed_results={"result = 42": 42},
    denied_operations=["DROP TABLE"],
)
async with sandbox as sb:
    result = await sb.execute("result = 42")
    assert result.return_value == 42
```

### Safety Assertions

```python
from agenticapi.testing import assert_code_safe, assert_policy_enforced, assert_intent_parsed
from agenticapi.interface.intent import IntentAction

assert_code_safe("x = 1 + 2")                          # passes
assert_code_safe("import os", denied_modules=["os"])    # raises AssertionError
assert_policy_enforced("x = 1", [CodePolicy()])         # passes
assert_intent_parsed("show orders", IntentAction.READ)  # passes
```

### Factory Fixtures

```python
from agenticapi.testing import create_test_app

app = create_test_app(
    policies=[CodePolicy(denied_modules=["os"])],
    llm_responses=["result = 1"],
    title="Test",
)
```

### E2E Example Tests

The E2E test suite exercises all 9 example apps via HTTP TestClient:

```python
# tests/e2e/test_examples.py
# - Imports each example app
# - Sends requests to every endpoint
# - Validates health checks, intent processing, error codes
# - Tests session continuity, scope enforcement, approval triggers
# - Skips examples requiring unavailable API keys
```

## Performance Benchmarks

| Benchmark | Target | File |
|---|---|---|
| Intent parsing (keyword) | < 50ms | `bench_intent_parsing.py` |
| Policy evaluation (4 policies) | < 15ms | `bench_policy_evaluation.py` |
| Static analysis (1000 lines) | < 50ms | `bench_static_analysis.py` |
| Sandbox startup + execution | < 100ms | `bench_sandbox_startup.py` |

Run with: `uv run pytest tests/benchmarks/ --benchmark-only`

## Test File Organization

```
tests/
    conftest.py                  Shared fixtures (sample_intent_raw, sample_code, dangerous_code)
    unit/
        test_app.py              AgenticApp creation, HTTP endpoints, error status codes
        test_intent.py           Intent model, IntentAction, IntentParser, IntentScope
        test_session.py          Session TTL, SessionManager CRUD, cleanup
        test_response.py         AgentResponse serialization, ResponseFormatter
        test_openapi.py          OpenAPI schema, Swagger UI, ReDoc, disabling, custom URLs
        test_params.py           HarnessDepends dependency injection
        test_fixtures.py         create_test_app factory
        test_mock_sandbox.py     MockSandbox patterns
        test_compat.py           REST route generation, FastAPI mount
        test_bugfix_regressions.py  Regression tests for all bug fixes
        harness/
            test_code_policy.py, test_data_policy.py, test_policy_evaluator.py
            test_runtime_policy.py, test_static_analysis.py, test_sandbox.py
            test_approval.py, test_monitors.py, test_validators.py
            test_audit_recorder.py, test_audit_exporters.py
        runtime/
            test_code_generator.py, test_context.py, test_tool_registry.py
            test_llm_backend.py, test_openai_backend.py, test_gemini_backend.py
            test_prompts.py, test_http_client_tool.py, test_cache_tool.py, test_queue_tool.py
        application/
            test_pipeline.py     DynamicPipeline stages, ordering, limits
        ops/
            test_ops_base.py     OpsAgent lifecycle, severity gating
        a2a/
            test_protocol.py, test_capability.py, test_trust.py
    integration/
        test_endpoint_flow.py    Full HTTP flow via ASGI TestClient
        test_harness_flow.py     Harness pipeline with policies, approval, monitors
        test_fastapi_compat.py   Mount compatibility
    e2e/
        test_full_request_cycle.py  Complete pipeline: LLM -> harness -> sandbox -> response
        test_examples.py         All 10 example apps with HTTP requests
    benchmarks/
        bench_intent_parsing.py, bench_policy_evaluation.py
        bench_static_analysis.py, bench_sandbox_startup.py
```
