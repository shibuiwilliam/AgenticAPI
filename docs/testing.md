# Testing Guide

## Test Suite Overview

| Category | Files | Tests | Purpose |
|---|---|---|---|
| Unit tests | 39 | ~450 | Individual module correctness |
| Integration tests | 3 | ~30 | Cross-module interaction |
| E2E tests | 2 | ~20 | Full HTTP request cycle |
| Benchmarks | 4 | 10 | Performance targets |
| **Total** | **48** | **~530** | **88% code coverage** |

## Running Tests

```bash
# All tests (excluding benchmarks)
uv run pytest --ignore=tests/benchmarks

# With coverage
uv run pytest --cov=src/agenticapi --cov-report=term-missing --ignore=tests/benchmarks

# Specific module
uv run pytest tests/unit/harness/test_static_analysis.py -xvs

# Only benchmarks
uv run pytest tests/benchmarks/

# Skip tests requiring LLM API keys
uv run pytest -m "not requires_llm"
```

## Test Patterns

### AgentTestCase (base class for agent tests)

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
```

### Mock Sandbox

```python
from agenticapi.testing import MockSandbox

sandbox = MockSandbox(
    allowed_results={"result = 42": 42},
    denied_operations=["DROP TABLE"],
)
```

### Safety Assertions

```python
from agenticapi.testing import assert_code_safe, assert_policy_enforced

assert_code_safe("x = 1 + 2")                          # passes
assert_code_safe("import os", denied_modules=["os"])    # raises AssertionError
assert_policy_enforced("x = 1", [CodePolicy()])         # passes
```

### Factory Fixtures

```python
from agenticapi.testing import create_test_app

app = create_test_app(
    policies=[CodePolicy(denied_modules=["os"])],
    llm_responses=["result = 1"],
)
```

## Performance Benchmarks

| Benchmark | Target | File |
|---|---|---|
| Intent parsing (keyword) | < 50ms | `bench_intent_parsing.py` |
| Policy evaluation (4 policies) | < 15ms | `bench_policy_evaluation.py` |
| Static analysis (1000 lines) | < 50ms | `bench_static_analysis.py` |
| Sandbox startup + execution | < 100ms | `bench_sandbox_startup.py` |

## Test File Organization

```
tests/
    conftest.py                  Shared fixtures (sample_intent_raw, sample_code, dangerous_code)
    unit/
        test_app.py              AgenticApp creation, HTTP endpoints, error status codes
        test_intent.py           Intent model, IntentAction, IntentParser, IntentScope
        test_session.py          Session TTL, SessionManager CRUD, cleanup
        test_response.py         AgentResponse serialization, ResponseFormatter
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
    integration/
        test_endpoint_flow.py    Full HTTP flow via ASGI TestClient
        test_harness_flow.py     Harness pipeline with policies, approval, monitors
        test_fastapi_compat.py   Mount compatibility
    e2e/
        test_full_request_cycle.py  Complete pipeline: LLM -> harness -> sandbox -> response
    benchmarks/
        bench_intent_parsing.py, bench_policy_evaluation.py
        bench_static_analysis.py, bench_sandbox_startup.py
```
