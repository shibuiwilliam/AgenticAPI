# Testing Strategy and Conventions

---

## Test Directory Structure

```
tests/
├── unit/                     # Fast, isolated, no I/O
│   ├── harness/              # HarnessEngine, policies, sandbox, audit
│   │   └── policy/           # Per-policy tests (budget, PII, injection)
│   ├── runtime/              # LLM backends, tools, memory, codegen
│   │   └── llm/              # Backend-specific tests
│   │   └── tools/            # @tool decorator, registry
│   ├── interface/            # Intent, response, stream, session
│   ├── dependencies/         # Depends(), scanner, solver
│   ├── a2a/                  # A2A protocol, capability, trust
│   ├── mesh/                 # AgentMesh, MeshContext
│   ├── observability/        # Tracing, metrics, propagation
│   ├── application/          # DynamicPipeline
│   ├── cli/                  # CLI subcommands (init, replay, eval)
│   ├── ops/                  # OpsAgent base
│   ├── test_openapi.py       # OpenAPI schema generation (inc. D7 typed requests)
│   ├── test_typed_intents.py # Intent[T] generic + scanner extraction
│   ├── test_dx_integration.py # Cross-feature integration
│   └── test_*.py             # Other unit tests
├── integration/              # Multi-module, may touch filesystem
├── e2e/                      # Full HTTP request/response via TestClient
│   ├── test_examples.py      # Tests for all 27 example apps
│   └── test_full_request_cycle.py
└── benchmarks/               # Performance regression (excluded from CI)
```

**Current counts:** 1,310 tests collected (excluding benchmarks), 27 e2e-tested example apps.

---

## Key Conventions

### MockBackend for deterministic testing

All tests that exercise the LLM path use `MockBackend` — never a real provider API. `MockBackend` supports:
- Pre-queued text responses (`add_response("...")`)
- Pre-queued tool call responses (`add_tool_response(ToolCall(...))`)
- `finish_reason` control (`"stop"`, `"tool_calls"`)
- `tool_choice` honoring (returns tool call when `tool_choice="required"`)
- Structured output (synthesises schema-conforming JSON for `Intent[T]`)

### E2E test pattern for examples

Every example gets a test class in `tests/e2e/test_examples.py`:

```python
class TestExampleNNName:
    @pytest.fixture
    def client(self) -> TestClient:
        app = _load_app("examples.NN_name.app")
        return TestClient(app, raise_server_exceptions=False)

    def test_health(self, client: TestClient) -> None:
        data = _assert_health_ok(client)
        assert "endpoint_name" in data["endpoints"]

    def test_clean_input(self, client: TestClient) -> None:
        data = _post_intent(client, "endpoint_name", "some intent")
        assert data["result"]["key"] == "expected"
```

Helpers `_load_app()`, `_post_intent()`, `_assert_health_ok()` are shared at module top.

### LLM-dependent tests

Tests requiring a real API key are either:
- Gated with `@pytest.mark.skipif(not os.environ.get("..._API_KEY"))`
- Accept multiple valid status codes: `{200, 202, 403}` (since LLM outputs vary)

### Policy tests

Each policy gets a dedicated test file in `tests/unit/harness/policy/`. Standard structure:
1. Positive cases (violations detected)
2. Negative cases (clean input passes)
3. Mode switching (detect/redact/block)
4. Configuration knobs (disabled_detectors, extra_patterns)
5. `evaluate_tool_call()` hook (E4 path)
6. `evaluate_intent_text()` hook (pre-LLM path)

---

## Quality Gates

Every task must pass before merging:

```bash
uv run ruff format --check src/ tests/ examples/
uv run ruff check src/ tests/ examples/
uv run mypy src/agenticapi/
uv run pytest --ignore=tests/benchmarks -q
```

Extensions:
```bash
uv run pytest extensions/agenticapi-claude-agent-sdk/tests -q
```

---

## Performance Targets

| Component | Target |
|---|---|
| `IntentParser.parse()` (keyword path) | < 50 ms |
| `PolicyEvaluator.evaluate()` | < 15 ms |
| Static AST analysis (1,000 lines) | < 50 ms |
| `ProcessSandbox` startup | < 100 ms |
| Streaming first-event latency | < 200 ms |
| Agent endpoint overhead (excl. LLM) | < 500 ms |

Benchmarks: `uv run pytest tests/benchmarks/ -v`
