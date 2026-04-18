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
│   ├── cli/                  # CLI subcommands (init, replay, eval, bump)
│   ├── ops/                  # OpsAgent base
│   ├── trace_inspector/      # Trace inspector routes (search, diff, stats, export)
│   ├── mcp_tools/            # HarnessMCPServer dispatch and audit
│   ├── playground/           # Playground UI and API routes
│   ├── workflow/             # Workflow engine, state, checkpoints
│   ├── test_openapi.py       # OpenAPI schema generation (inc. D7 typed requests)
│   ├── test_typed_intents.py # Intent[T] generic + scanner extraction
│   ├── test_dx_integration.py # Cross-feature integration
│   └── test_*.py             # Other unit tests
├── integration/              # Multi-module, may touch filesystem
│   └── llm/                  # Real-provider integration tests (API key gated)
├── e2e/                      # Full HTTP request/response via TestClient
│   ├── test_examples.py      # Tests for all 32 example apps
│   └── test_full_request_cycle.py
└── benchmarks/               # Performance regression (excluded from CI)
```

**Current counts:** 1,507 tests collected (excluding benchmarks), 32 e2e-tested example apps, 6 real-provider integration tests.

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

## Agentic Loop Tests

Tests in `tests/unit/runtime/test_agentic_loop.py` follow this pattern:

1. Queue `MockBackend` responses: `add_tool_call_response()` for iterations that return tool calls, `add_response()` for the final text.
2. Create a `ToolRegistry` with `_FakeTool` instances.
3. Call `run_agentic_loop(llm=backend, tools=registry, ...)`.
4. Assert: `result.iterations`, `result.tool_calls_made`, `result.final_text`.

Key test scenarios:
- Happy path (2 iterations: tool → final text)
- Multi-tool dispatch (2 tools in one iteration)
- Three-iteration chain (tool → tool → final)
- Max iterations enforcement
- Harness integration (tool calls go through `HarnessEngine.call_tool`)
- Unknown tool recovery (error message sent back to LLM)
- Tool failure propagation (`ToolError`)
- Budget tracking across iterations
- Token accumulation

---

## Workflow Engine Tests

Tests in `tests/unit/workflow/test_workflow_engine.py`:

1. Define `WorkflowState` subclasses with typed fields.
2. Register steps with `@workflow.step("name")`.
3. Call `workflow.run()` and assert `result.steps_executed`, `result.final_state`.

Key test scenarios:
- Linear workflow (A → B → C)
- Conditional branching (decide → high or low)
- Parallel execution (start → [task_a, task_b])
- Checkpoint pause and resume
- Retry on transient failure
- Step timeout
- Mermaid graph export
- WorkflowStore persistence (InMemory and SQLite)
- WorkflowContext.llm_generate()

---

## Playground Tests

Tests in `tests/unit/playground/test_playground.py`:

1. Create `AgenticApp(playground_url="/_playground")`.
2. Use `TestClient` to hit playground routes.
3. Assert HTML served, endpoints listed, chat proxied, traces returned.

Key test scenarios:
- HTML page served at `/_playground`
- Playground disabled returns 404
- Custom URL works
- `/api/endpoints` lists registered endpoints
- `/api/chat` proxies to agent endpoint
- `/api/chat` returns 404 for unknown endpoint
- Health and agent endpoints still work alongside playground

### Trace Inspector Tests

Tests: `tests/unit/trace_inspector/test_trace_inspector.py` (18 tests).

1. Inject traces directly into `AuditRecorder._traces` (bypasses async `record()`).
2. Use `TestClient` to hit `/_trace` routes.
3. Assert search, detail, diff, stats, and export all return correct data.

Key test scenarios:
- HTML page served at `/_trace`
- Disabled returns 404
- Custom URL works
- Search returns injected traces
- Status filter (success, error, denied)
- Trace detail by ID
- Diff of two traces detects changed fields
- Identical traces report `identical: true`
- Stats aggregation
- Export produces JSON with `Content-Disposition: attachment`

### MCP Tools Tests

Tests: `tests/unit/mcp_tools/test_harness_mcp.py` (6 tests).

1. Use `_FakeTool` implementing the `Tool` protocol.
2. Test `HarnessEngine.call_tool()` dispatch with policy evaluation.
3. Verify audit recording with `mcp:` endpoint prefix.

Key test scenarios:
- `ImportError` raised when `mcp` package is missing
- Harness `call_tool()` invoked for tool calls
- Policy evaluation passes/denies tool calls
- Direct invocation without harness
- Multiple tools registered correctly
- Audit trail recorded with `mcp:{tool_name}` endpoint

### Provider Integration Tests

Tests: `tests/integration/llm/test_real_{anthropic,openai,gemini}.py` (6 tests total).

Gated by environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`). Each test:

1. Creates a real backend with the API key.
2. Sends a prompt with a `calculator` tool definition.
3. Asserts the LLM returns `tool_calls` with `finish_reason="tool_calls"`.
4. Sends the tool result back and asserts the LLM produces a final `"stop"` answer containing `"42"`.

Run manually: `ANTHROPIC_API_KEY=sk-... uv run pytest tests/integration/llm/ -v --timeout=60`

### Provider Tool Format Tests

Tests: `tests/unit/runtime/llm/test_{anthropic,openai,gemini}_tool_format.py`.

Verify that `_normalize_tool()` and `_build_request_kwargs()` correctly translate:
- Framework generic format → provider-specific tool definitions
- Multi-turn messages with `tool_calls` → provider-specific content blocks
- Tool result messages with `tool_call_id` → provider-specific result format

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
