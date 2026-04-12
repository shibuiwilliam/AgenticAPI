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
