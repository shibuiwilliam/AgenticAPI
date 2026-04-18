# Extending AgenticAPI

Step-by-step guides for adding new features to the framework.

---

## Adding a New Policy

1. Create `src/agenticapi/harness/policy/my_policy.py` inheriting from `Policy` (in `base.py`).
2. Implement `evaluate(*, code, intent_action, intent_domain, **kwargs) -> PolicyResult`.
3. **Optional:** Override `evaluate_intent_text(*, intent_text, ...)` for pre-LLM text scanning (see `PIIPolicy`, `PromptInjectionPolicy` for the pattern).
4. **Optional:** Override `evaluate_tool_call(*, tool_name, arguments, ...)` for E4 tool-first path enforcement.
5. Export from `harness/policy/__init__.py` and `harness/__init__.py`.
6. Add tests in `tests/unit/harness/policy/test_my_policy.py`.
7. If public API, export from `src/agenticapi/__init__.py` and add to `__all__`.
8. Add a row to the "Key Types" table in `CLAUDE.md`.

Reference: `pii_policy.py` (comprehensive, all 3 hooks), `prompt_injection_policy.py` (text scanning), `budget_policy.py` (stateful with pre/post estimation).

---

## Adding a New Tool

1. Create `src/agenticapi/runtime/tools/my_tool.py` implementing the `Tool` protocol.
2. Implement `definition` property → `ToolDefinition` and `async invoke(**kwargs)`.
3. Export from `runtime/tools/__init__.py`.
4. Add tests in `tests/unit/runtime/tools/test_my_tool.py`.

**Easier: use `@tool` decorator** (no class needed):

```python
from agenticapi import tool

@tool(description="Look up a user by ID")
async def get_user(user_id: int) -> dict:
    return {"id": user_id, "name": "Alice"}

registry.register(get_user)
```

Reference: `decorator.py` for the implementation, `database.py` for the class-based pattern.

---

## Adding a New LLM Backend

1. Create `src/agenticapi/runtime/llm/my_backend.py` implementing `LLMBackend` protocol.
2. Implement `generate()`, `generate_stream()`, `model_name` property.
3. Handle `ToolCall` parsing from provider responses (see CLAUDE.md > Implementation Blueprints > E8 for the pattern).
4. Use `RetryConfig` from `retry.py` for transient failure handling.
5. Constructor: accept `api_key`, `model`, `max_tokens`, `timeout`.
6. Read API key from env var with explicit parameter override.
7. Export from `runtime/llm/__init__.py`.
8. Add tests in `tests/unit/runtime/llm/test_my_backend.py`.

Reference: `anthropic.py`, `openai.py`, `gemini.py`, `mock.py`.

---

## Adding a New Example

1. Create `examples/NN_my_example/app.py` (no `__init__.py` needed).
2. Include docstring with: purpose, features demonstrated, run command, curl walkthrough.
3. Use `TYPE_CHECKING` for `AgentContext` import.
4. Use broad `IntentScope` wildcards (`*.read`, `*.analyze`) — LLMs classify domains unpredictably.
5. Pass `tools=tools` to `AgenticApp()` if using tools with LLM.
6. Add E2E tests in `tests/e2e/test_examples.py` following the `TestExampleNNName` pattern.
7. Add table entry AND detailed section in `examples/README.md`.
8. Update example count in `CLAUDE.md` and `ROADMAP.md`.

Reference: `22_safety_policies/app.py` (focused, ~200 LOC), `25_harness_playground/app.py` (production starter).

---

## Adding a CLI Subcommand

1. Create `src/agenticapi/cli/my_command.py` with the command function.
2. Register in `src/agenticapi/cli/main.py`'s command dispatch.
3. Add tests in `tests/unit/cli/test_my_command.py`.

Reference: `init.py` (generates files), `replay.py` (reads audit store), `eval.py` (runs judges).

---

## Adding Mesh Roles

```python
from agenticapi import AgenticApp, AgentMesh

app = AgenticApp(title="My Mesh")
mesh = AgentMesh(app=app, name="pipeline")

@mesh.role(name="worker")
async def worker(payload: str, ctx: MeshContext) -> dict:
    return {"result": f"processed {payload}"}

@mesh.orchestrator(name="run", roles=["worker"])
async def run(intent, mesh_ctx):
    return await mesh_ctx.call("worker", intent.raw)
```

Reference: `examples/27_multi_agent_pipeline/app.py`, `src/agenticapi/mesh/mesh.py`.

---

## Adding an Extension Package

1. Create `extensions/my-extension/` with layout:
   ```
   extensions/my-extension/
       pyproject.toml   # depends on agenticapi>=0.1.0 + heavy library
       README.md
       src/my_extension/
           __init__.py   # public API via __all__
           py.typed      # PEP 561 marker
       tests/
           conftest.py   # stub optional heavy deps
           test_*.py
   ```
2. Use **lazy imports** — `import my_extension` must never fail.
3. Tests run **offline** via stub module in `conftest.py`.
4. Errors inherit from `agenticapi.AgenticAPIError`.

Reference: `extensions/agenticapi-claude-agent-sdk/`.

---

## Using the Agentic Loop

The multi-turn agentic loop (`runtime/loop.py`) makes endpoints genuinely agentic — the LLM autonomously decides which tools to call and reasons over their results.

1. Register tools via `ToolRegistry` or `@tool`.
2. Configure the app with `llm=`, `harness=`, `tools=`.
3. Optionally set `loop_config=LoopConfig(max_iterations=5)` on the endpoint.
4. The loop runs automatically when the LLM returns tool calls.

```python
from agenticapi import AgenticApp, tool, LoopConfig

@tool(description="Get weather data")
async def get_weather(city: str) -> dict:
    return {"temp": 22, "rain": 80}

app = AgenticApp(harness=harness, llm=backend, tools=registry)

@app.agent_endpoint(name="advisor", loop_config=LoopConfig(max_iterations=5))
async def advisor(intent, context):
    return {}  # fallback — loop handles tool dispatch
```

For standalone use outside of endpoints:

```python
from agenticapi import run_agentic_loop, LoopConfig

result = await run_agentic_loop(
    llm=backend, tools=registry, harness=harness,
    prompt=prompt, config=LoopConfig(max_iterations=10),
)
print(result.final_text, result.tool_calls_made)
```

Reference: `src/agenticapi/runtime/loop.py`, `examples/29_agentic_loop/app.py`.

---

## Building Workflow-Based Agents

The workflow engine (`workflow/`) lets you define multi-step agent processes with typed state, conditional branching, and checkpoint pauses.

1. Subclass `WorkflowState` with typed fields.
2. Create an `AgentWorkflow[MyState]` and register steps with `@workflow.step()`.
3. Each step returns the next step name (str), parallel steps (list[str]), or None to end.
4. Attach to an endpoint: `@app.agent_endpoint(workflow=my_workflow)`.

```python
from agenticapi import AgentWorkflow, WorkflowState, WorkflowContext

class MyState(WorkflowState):
    data: str = ""

workflow = AgentWorkflow(name="pipeline", state_class=MyState)

@workflow.step("start")
async def start(state: MyState, ctx: WorkflowContext) -> str:
    state.data = await ctx.call_tool("fetch_data", query="test")
    return "analyze"

@workflow.step("analyze")
async def analyze(state: MyState, ctx: WorkflowContext) -> None:
    state.data += " — analyzed"
    return None  # workflow complete

@app.agent_endpoint(name="process", workflow=workflow)
async def handler(intent, context):
    return {}  # fallback
```

Reference: `src/agenticapi/workflow/`, `examples/30_agent_workflow/app.py`.

---

## Using the Agent Playground

The playground provides a self-hosted debugger UI at `/_playground`.

1. Enable: `AgenticApp(playground_url="/_playground")`.
2. Open `http://localhost:8000/_playground` in a browser.
3. Select an endpoint, type an intent, and see the response + trace.

The playground is disabled by default. It requires no external dependencies — the UI is vanilla HTML/JS/CSS served inline.

Reference: `src/agenticapi/playground/routes.py`.

---

## Using the Trace Inspector

The trace inspector provides a self-hosted UI for searching, diffing,
and exporting execution traces.

1. Enable: `AgenticApp(harness=harness, trace_url="/_trace")`.
2. Open `http://localhost:8000/_trace` in a browser.
3. Search traces by endpoint, status, tool, date, cost.
4. Click a trace ID to see the full timeline.
5. Use the Diff tab to compare two traces side-by-side.
6. Use the Stats tab for cost breakdown by endpoint and tool.
7. Export traces as JSON compliance reports.

Requires a `HarnessEngine` with an `AuditRecorder` to have data.
Disabled by default. No external dependencies.

Reference: `src/agenticapi/trace_inspector/routes.py`.

---

## Exposing Tools via Harness-Governed MCP

`HarnessMCPServer` exposes registered `@tool` functions as MCP tools
with full harness governance. Every tool call from an external AI
assistant goes through `HarnessEngine.call_tool()`.

```python
from agenticapi.mcp_tools import HarnessMCPServer

app = AgenticApp(harness=harness, tools=registry)
HarnessMCPServer(app, path="/mcp/tools")
```

1. Register tools in a `ToolRegistry`.
2. Configure a `HarnessEngine` with policies.
3. Create `HarnessMCPServer(app, path="/mcp/tools")`.
4. Test: `npx @modelcontextprotocol/inspector http://localhost:8000/mcp/tools`.

Requires `pip install agentharnessapi[mcp]`. Unlike `expose_as_mcp()`
(which exposes agent endpoints as MCP tools), `HarnessMCPServer`
exposes the registered `@tool` functions themselves.

Reference: `src/agenticapi/mcp_tools/server.py`, `examples/32_harness_mcp_tools/app.py`.
