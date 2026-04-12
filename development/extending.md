# Extending AgenticAPI

Step-by-step guides for adding new features to the framework.

---

## Adding a New Policy

Policies are the primary extensibility mechanism for the harness layer. Every policy implements the `Policy` protocol from `harness/policy/base.py`.

### Steps

1. **Create the module:**
   `src/agenticapi/harness/policy/my_policy.py`

2. **Implement the `Policy` protocol:**
   ```python
   from agenticapi.harness.policy.base import Policy, PolicyResult

   class MyPolicy(Policy):
       model_config = ConfigDict(extra="forbid")
       # Configuration fields (Pydantic)
       threshold: float = 0.8

       def evaluate(
           self, *, code: str, intent_action: str, intent_domain: str, **kwargs: Any
       ) -> PolicyResult:
           violations = []
           warnings = []
           # ... check code/intent ...
           return PolicyResult(
               policy_name="my_policy",
               allowed=len(violations) == 0,
               violations=violations,
               warnings=warnings,
           )
   ```

3. **Optional: implement `evaluate_tool_call`** for the tool-first path (Phase E4):
   ```python
   def evaluate_tool_call(
       self, *, tool_name: str, arguments: dict[str, Any],
       intent_action: str, intent_domain: str, **kwargs: Any,
   ) -> PolicyResult:
       ...
   ```

4. **Export from `harness/policy/__init__.py`:**
   Add the import and include the class name in `__all__`.

5. **Export from `harness/__init__.py`:**
   Add the import and include the class name in `__all__`.

6. **Optionally export from `src/agenticapi/__init__.py`** if it is part of the public API.

7. **Add tests:**
   `tests/unit/harness/test_my_policy.py`

### Reference implementations
- `code_policy.py` — simple deny-list check
- `prompt_injection_policy.py` — regex pattern matching with categories
- `pii_policy.py` — detection + redaction with Luhn validation
- `budget_policy.py` — stateful cost tracking across scopes

---

## Adding a New Tool

Tools implement the `Tool` protocol from `runtime/tools/base.py`. There are two approaches.

### Approach A: Protocol class

1. **Create the module:**
   `src/agenticapi/runtime/tools/my_tool.py`

2. **Implement the `Tool` protocol:**
   ```python
   from agenticapi.runtime.tools.base import Tool, ToolDefinition

   class MyTool(Tool):
       @property
       def definition(self) -> ToolDefinition:
           return ToolDefinition(
               name="my_tool",
               description="Does something useful",
               parameters_schema={"type": "object", "properties": {...}},
           )

       async def invoke(self, **kwargs: Any) -> Any:
           # ... implementation ...
           return result
   ```

3. **Export from `runtime/tools/__init__.py`.**

4. **Add tests:** `tests/unit/runtime/test_my_tool.py`

### Approach B: `@tool` decorator

For simple tools, use the decorator which infers the schema from type hints:

```python
from agenticapi import tool

@tool(description="Look up a user by ID")
async def get_user(user_id: int) -> dict:
    return {"id": user_id, "name": "Alice"}

registry.register(get_user)
```

### Reference: `database.py` for the protocol pattern, `decorator.py` for the decorator.

---

## Adding a New LLM Backend

LLM backends implement the `LLMBackend` protocol from `runtime/llm/base.py`.

### Steps

1. **Create the module:**
   `src/agenticapi/runtime/llm/my_backend.py`

2. **Implement the protocol:**
   ```python
   from agenticapi.runtime.llm.base import LLMBackend, LLMPrompt, LLMResponse

   class MyBackend(LLMBackend):
       def __init__(
           self, *, api_key: str | None = None, model: str = "default",
           max_tokens: int = 4096, timeout: float = 30.0,
       ) -> None:
           self._api_key = api_key or os.environ.get("MY_API_KEY", "")
           self._model = model
           self._max_tokens = max_tokens
           self._timeout = timeout

       @property
       def model_name(self) -> str:
           return self._model

       async def generate(self, prompt: LLMPrompt) -> LLMResponse:
           # ... call the API ...

       async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
           # ... streaming variant ...
   ```

3. **Constructor conventions:**
   - Accept `api_key` with explicit parameter override.
   - Read from environment variable as fallback.
   - Accept `model`, `max_tokens`, `timeout`.

4. **Export from `runtime/llm/__init__.py`.**

5. **Add tests:** `tests/unit/runtime/test_my_backend.py`. Use `unittest.mock.patch` or a stub HTTP client to avoid real API calls in CI.

### Reference: `anthropic.py`, `openai.py`, `gemini.py`.

---

## Adding a New Example

Examples live in `examples/NN_my_example/app.py`. No `__init__.py` needed.

### Steps

1. **Create the directory and app file:**
   `examples/NN_my_example/app.py`

2. **Include a module docstring** with:
   - Prerequisites (what to install, what env vars to set)
   - Run command: `agenticapi dev --app examples.NN_my_example.app:app`
   - Test commands: `curl` examples for each endpoint

3. **Coding conventions:**
   - Use `TYPE_CHECKING` for `AgentContext` import.
   - Use broad `IntentScope` wildcards (`*.read`, `*.analyze`) — LLMs may classify domains unpredictably.
   - Pass `tools=tools` to `AgenticApp()` if using tools with LLM.

4. **Naming convention:** Two-digit number, underscore-separated descriptive name (e.g. `14_dependency_injection`).

5. **Add e2e tests** in `tests/e2e/test_examples.py`:
   - New test class: `TestExampleNNMyExample`
   - Test `/health` and at least one endpoint.
   - Tests must pass without API keys (direct handler mode).

6. **Update `examples/README.md`** with the new example in the table.

---

## Adding a New Extension Package

Extensions live under `extensions/<package-name>/` with their own `pyproject.toml` and are published separately from core.

### Directory layout

```
extensions/my-extension/
    pyproject.toml           # Depends on agenticapi>=0.1.0 + heavy deps
    README.md                # User-facing docs
    src/my_extension/
        __init__.py          # Public API via __all__
        py.typed             # PEP 561 marker
        ...
    tests/
        conftest.py          # Stub heavy deps for offline testing
        test_*.py
    examples/
```

### Key rules

1. **`pyproject.toml`**: Depend on `agenticapi>=0.1.0` plus the wrapped library. Pin carefully (e.g., `>=X.Y,<X.Y+1`).

2. **Lazy imports**: The top-level `import my_extension` must never fail, even when the optional heavy dep is absent. Import the wrapped library inside functions/methods and raise a friendly `*NotInstalledError` on first use.

3. **Offline tests**: Install a stub module in `conftest.py` that mimics the wrapped library's public surface. Tests must run without network and without the real heavy dependency.

4. **Error hierarchy**: Errors should inherit from `agenticapi.AgenticAPIError` so callers can catch both core and extension errors uniformly.

5. **Installation for development:**
   ```bash
   uv pip install -e extensions/my-extension --no-deps
   uv run pytest extensions/my-extension/tests
   uv run mypy extensions/my-extension/src
   ```

### Reference: `extensions/agenticapi-claude-agent-sdk/`

---

## Quality Gates Checklist

Before any feature is considered complete, verify all of the following:

- [ ] Tests written and passing: `uv run pytest --ignore=tests/benchmarks`
- [ ] Code formatted: `uv run ruff format src/ tests/ examples/`
- [ ] Lint clean: `uv run ruff check src/ tests/ examples/`
- [ ] Type check clean: `uv run mypy src/agenticapi/`
- [ ] Exports added to the appropriate `__init__.py` files
- [ ] Public APIs have Google-style docstrings
- [ ] Public APIs have type hints
- [ ] If adding a new example: e2e test added, `examples/README.md` updated
- [ ] If adding a new public type: exported from `src/agenticapi/__init__.py` and added to `__all__`
