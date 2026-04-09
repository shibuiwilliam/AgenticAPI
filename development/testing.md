# Testing Guide

## Test Suite Overview

| Category | Files | Tests | Purpose |
|---|---|---|---|
| Unit tests | 51 | ~613 | Individual module correctness |
| Integration tests | 4 | ~28 | Cross-module interaction |
| E2E tests | 2 | ~100 | Full HTTP request cycle + all 12 example apps |
| Benchmarks | 4 | 10 | Performance regression detection |
| **Total** | **67** | **713** | **87% code coverage** |

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

# Only E2E (exercises all 12 examples)
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

The E2E test suite exercises all 12 example apps via HTTP TestClient:

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
        test_app.py              AgenticApp creation, HTTP endpoints, error status codes (25 tests)
        test_intent.py           Intent model, IntentAction, IntentParser, IntentScope (30 tests)
        test_session.py          Session TTL, SessionManager CRUD, cleanup (20 tests)
        test_response.py         AgentResponse serialization, ResponseFormatter (18 tests)
        test_security.py         Authentication, authorization, all 4 schemes (39 tests)
        test_openapi.py          OpenAPI schema, Swagger UI, ReDoc, disabling (12 tests)
        test_background_tasks.py AgentTasks add/execute/error handling (11 tests)
        test_mcp_compat.py       MCP compatibility layer (27 tests)
        test_file_response.py    FileResult and custom response types (12 tests)
        test_file_upload.py      UploadFile, UploadedFiles multipart handling (7 tests)
        test_custom_responses.py HTMLResult, PlainTextResult, Response passthrough (10 tests)
        test_params.py           HarnessDepends dependency injection (3 tests)
        test_fixtures.py         create_test_app factory (5 tests)
        test_mock_sandbox.py     MockSandbox patterns (8 tests)
        test_compat.py           REST route generation, FastAPI mount (12 tests)
        test_bugfix_regressions.py  Regression tests for all bug fixes (17 tests)
        test_agent_test_case.py  AgentTestCase helper class (13 tests)
        test_benchmark_runner.py BenchmarkRunner execution (8 tests)
        test_cli_console.py      CLI console interface (5 tests)
        test_htmx.py             HtmxHeaders parsing, htmx_response_headers builder (9 tests)
        harness/
            test_code_policy.py        CodePolicy: denied modules, eval/exec (16 tests)
            test_data_policy.py        DataPolicy: DDL, DML, table access (16 tests)
            test_policy_evaluator.py   PolicyEvaluator aggregation (10 tests)
            test_runtime_policy.py     RuntimePolicy: complexity limits (8 tests)
            test_static_analysis.py    AST safety checks (29 tests)
            test_sandbox.py            ProcessSandbox execution (14 tests)
            test_approval.py           Approval workflow, rules, notifiers (21 tests)
            test_monitors.py           Resource and output monitors (8 tests)
            test_validators.py         Output validation (9 tests)
            test_audit_recorder.py     Audit recording (9 tests)
            test_audit_exporters.py    Audit export formats (8 tests)
        runtime/
            test_code_generator.py     Code generation from intents (9 tests)
            test_context.py            AgentContext, ContextWindow (15 tests)
            test_tool_registry.py      Tool registration and discovery (9 tests)
            test_llm_backend.py        Base LLM backend interface (11 tests)
            test_openai_backend.py     OpenAI API integration (15 tests)
            test_gemini_backend.py     Google Gemini API integration (15 tests)
            test_prompts.py            LLM prompting and templates (15 tests)
            test_http_client_tool.py   HTTP client tool (11 tests)
            test_cache_tool.py         Caching tool (12 tests)
            test_queue_tool.py         Queue tool (14 tests)
        application/
            test_pipeline.py           DynamicPipeline stages, ordering (12 tests)
        ops/
            test_ops_base.py           OpsAgent lifecycle, severity gating (10 tests)
        a2a/
            test_protocol.py           A2A message types and routing (8 tests)
            test_capability.py         Agent capability negotiation (7 tests)
            test_trust.py              Trust and permission management (10 tests)
    integration/
        test_auth_flow.py        Full authentication flow through HTTP (11 tests)
        test_harness_flow.py     Harness blocking dangerous code (10 tests)
        test_endpoint_flow.py    Complete endpoint request flow (4 tests)
        test_fastapi_compat.py   FastAPI mount compatibility (3 tests)
    e2e/
        test_examples.py         All 12 example apps with HTTP requests (90 tests)
        test_full_request_cycle.py  Complete pipeline: LLM -> harness -> sandbox (10 tests)
    benchmarks/
        bench_intent_parsing.py     Intent parsing performance
        bench_policy_evaluation.py  Policy evaluation speed
        bench_static_analysis.py    Static analysis performance
        bench_sandbox_startup.py    Sandbox startup time
```
