# Testing Guide

## Current Suite Shape

The live tree currently contains:

- `65` test files under `tests/`
- `1,016` collected core tests
- `20` runnable example apps exercised by the E2E suite
- `6` extension test files and `38` extension tests for `agenticapi-claude-agent-sdk`

The test inventory has moved quickly. Prefer the live tree over stale hard-coded file counts in older docs.

## Directory Layout

```text
tests/
    unit/           Core behavior, regressions, streaming, typed intents, observability
    integration/    Cross-module request and auth flows
    e2e/            Full example-app and request-cycle coverage
    benchmarks/     Performance regression checks

extensions/agenticapi-claude-agent-sdk/tests/
    Offline extension test suite with stubbed SDK behavior
```

## What The Core Suite Covers

High-signal coverage areas in the current tree:

- app lifecycle and HTTP behavior
- intent parsing and typed intents
- dependency injection and route-level dependencies
- harness policies, sandbox, approval workflow, and audit
- observability helpers and propagation
- file handling, HTMX, custom responses, and OpenAPI
- tool registry, `@tool`, and native tool-call data types
- streaming events, replay, resume, and autonomy escalation
- end-to-end validation of all example apps

## Running Tests

```bash
# All core tests
uv run pytest

# Faster local loop
uv run pytest --ignore=tests/benchmarks

# With coverage
uv run pytest --cov=src/agenticapi --cov-report=term-missing --ignore=tests/benchmarks

# Focused directories
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/e2e -v

# Specific modules
uv run pytest tests/unit/test_streaming.py -xvs
uv run pytest tests/unit/test_typed_intents.py -xvs
uv run pytest tests/unit/harness/policy/test_budget_policy.py -xvs

# Benchmarks
uv run pytest tests/benchmarks

# Skip tests requiring real provider keys
uv run pytest -m "not requires_llm"

# Extension suite
uv pip install -e extensions/agenticapi-claude-agent-sdk --no-deps
uv run pytest extensions/agenticapi-claude-agent-sdk/tests
```

## Common Test Helpers

### `AgentTestCase`

Use `AgentTestCase` for endpoint-centric tests that need an app, mock LLM responses, or harness policies.

### `mock_llm`

Use `mock_llm(...)` when you need deterministic LLM behavior without touching provider SDKs.

### `MockSandbox`

Use `MockSandbox` when the test should exercise sandbox orchestration without spawning a real subprocess.

### Assertion helpers

Use `assert_code_safe`, `assert_policy_enforced`, and related helpers when the test is really about policy semantics rather than HTTP behavior.

## E2E Expectations

`tests/e2e/test_examples.py` is important because it protects the public surface area of the framework:

- every example app still imports
- auto-registered routes still behave as documented
- framework features continue to compose in real apps, not just in isolated unit tests

When adding a feature that changes documented behavior, update the relevant example and then extend the E2E suite.

## Current Hot Spots

If you change any of the following modules, run their focused tests before the full suite:

- `src/agenticapi/app.py`
- `src/agenticapi/interface/intent.py`
- `src/agenticapi/interface/stream.py`
- `src/agenticapi/dependencies/*`
- `src/agenticapi/harness/*`
- `src/agenticapi/runtime/llm/*`
- `src/agenticapi/observability/*`

## Practical Rule

Do not rely on a single unit test file to validate framework behavior. For user-facing features, keep the coverage stack layered:

1. unit tests for the local mechanism
2. integration tests for request-path behavior
3. example or E2E coverage for public API reality
