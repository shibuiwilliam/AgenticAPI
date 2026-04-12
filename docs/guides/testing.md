# Testing Guide

## Current Test Inventory

The live repository currently contains:

- `65` core test files under `tests/`
- `1,016` collected core tests
- `20` example apps exercised by the E2E suite
- `6` extension test files and `38` extension tests for `agenticapi-claude-agent-sdk`

## Directory Structure

```text
tests/
    unit/           Core behavior, regressions, streaming, typed intents, observability
    integration/    Cross-module request and auth flows
    e2e/            Example apps and full request-cycle coverage
    benchmarks/     Performance regression checks
```

## What The Suite Covers

Major coverage areas in the current tree:

- `AgenticApp` request lifecycle and HTTP behavior
- intent parsing and typed intents
- dependency injection and route-level dependencies
- harness policies, sandbox, approval workflow, and audit
- observability helpers and propagation
- file handling, HTMX, response types, and OpenAPI
- tool registration, `@tool`, and native tool-call data types
- streaming events, replay, resume, and autonomy escalation
- end-to-end validation of all example apps

## Running Tests

```bash
# All tests
uv run pytest

# Faster loop
uv run pytest --ignore=tests/benchmarks

# With coverage
uv run pytest --cov=src/agenticapi --cov-report=term-missing --ignore=tests/benchmarks

# Focused suites
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/e2e -v

# Specific areas
uv run pytest tests/unit/test_streaming.py -xvs
uv run pytest tests/unit/test_typed_intents.py -xvs
uv run pytest tests/unit/harness/policy/test_budget_policy.py -xvs
uv run pytest tests/unit/observability/test_metrics.py -xvs

# Benchmarks
uv run pytest tests/benchmarks

# Skip provider-key tests
uv run pytest -m "not requires_llm"

# Extension tests
uv pip install -e extensions/agenticapi-claude-agent-sdk --no-deps
uv run pytest extensions/agenticapi-claude-agent-sdk/tests
```

## Common Helpers

### `AgentTestCase`

Use `AgentTestCase` when the test needs an app, a handler, and optional mock LLM or policy configuration.

### `mock_llm`

Use `mock_llm(...)` for deterministic LLM behavior without provider SDKs.

### `MockSandbox`

Use `MockSandbox` when the test is about orchestration around sandbox execution rather than the real subprocess runtime.

## E2E Guidance

`tests/e2e/test_examples.py` protects the public surface area of the framework. When a feature changes user-facing behavior:

1. update the relevant example
2. extend or adjust the E2E coverage

## Current Hot Paths

Run focused tests when you change:

- `src/agenticapi/app.py`
- `src/agenticapi/interface/intent.py`
- `src/agenticapi/interface/stream.py`
- `src/agenticapi/dependencies/*`
- `src/agenticapi/harness/*`
- `src/agenticapi/runtime/llm/*`
- `src/agenticapi/observability/*`
