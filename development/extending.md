# Extending AgenticAPI

Step-by-step guides for adding new components to the framework.

## Adding a New Policy

Policies evaluate generated code before sandbox execution. They are pure synchronous functions with no I/O.

1. Create `src/agenticapi/harness/policy/my_policy.py`:

```python
from agenticapi.harness.policy.base import Policy, PolicyResult

class MyPolicy(Policy):
    """Description of what this policy checks."""

    my_threshold: int = 100  # Pydantic fields for configuration

    def evaluate(
        self,
        *,
        code: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: object,
    ) -> PolicyResult:
        violations = []
        warnings = []

        if len(code) > self.my_threshold:
            violations.append(f"Code exceeds threshold of {self.my_threshold}")

        return PolicyResult(
            allowed=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            policy_name=type(self).__name__,
        )
```

2. Export from `harness/policy/__init__.py` and `harness/__init__.py`
3. Add tests in `tests/unit/harness/test_my_policy.py`
4. Optionally export from `src/agenticapi/__init__.py` for public API

## Adding a New Tool

Tools provide agents with access to external systems. They implement the `Tool` protocol.

1. Create `src/agenticapi/runtime/tools/my_tool.py`:

```python
from typing import Any
from agenticapi.runtime.tools.base import Tool, ToolDefinition, ToolCapability

class MyTool:
    def __init__(self, *, name: str = "my_tool", description: str = "...") -> None:
        self._definition = ToolDefinition(
            name=name,
            description=description,
            capabilities=[ToolCapability.READ],
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The query to execute"},
                },
            },
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def invoke(self, **kwargs: Any) -> Any:
        query = kwargs.get("query", "")
        # ... tool logic ...
        return result
```

2. Export from `runtime/tools/__init__.py`
3. Add tests in `tests/unit/runtime/test_my_tool.py`
4. Reference: `database.py`, `cache.py`, `http_client.py`, `queue.py`

## Adding a New LLM Backend

LLM backends implement the `LLMBackend` protocol for code generation and intent parsing.

1. Create `src/agenticapi/runtime/llm/my_backend.py`:

```python
from agenticapi.runtime.llm.base import LLMBackend, LLMPrompt, LLMResponse, LLMChunk, LLMUsage
from agenticapi.exceptions import CodeGenerationError

class MyBackend:
    def __init__(
        self,
        *,
        model: str = "my-model-v1",
        api_key: str | None = None,
        max_tokens: int = 4096,
        timeout: float = 120.0,
    ) -> None:
        import os
        resolved_key = api_key or os.environ.get("MY_API_KEY")
        if not resolved_key:
            raise ValueError("API key required via parameter or MY_API_KEY env var")
        self._model = model
        self._client = MySDK(api_key=resolved_key, timeout=timeout)

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        try:
            result = await self._client.generate(...)
            return LLMResponse(
                content=result.text,
                usage=LLMUsage(input_tokens=result.input, output_tokens=result.output),
                model=self._model,
            )
        except Exception as exc:
            raise CodeGenerationError(f"MyBackend failed: {exc}") from exc

    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
        try:
            async for chunk in self._client.stream(...):
                yield LLMChunk(content=chunk.text, is_final=False)
            yield LLMChunk(content="", is_final=True)
        except Exception as exc:
            raise CodeGenerationError(f"MyBackend streaming failed: {exc}") from exc
```

2. Export from `runtime/llm/__init__.py`
3. Add tests in `tests/unit/runtime/test_my_backend.py` (mock the SDK client)
4. Reference: `anthropic.py`, `openai.py`, `gemini.py`

## Adding a New Example

1. Create `examples/NN_my_example/app.py` (no `__init__.py` needed)
2. Include a comprehensive docstring with:
   - What features are demonstrated
   - Prerequisites (API keys, pip installs)
   - Run command (`uvicorn` and `agenticapi dev`)
   - curl commands for every endpoint
3. Key patterns:
   - Use `TYPE_CHECKING` for `AgentContext` import
   - Use broad `IntentScope` wildcards (`*.read`, `*.analyze`) — LLMs classify domains unpredictably
   - Pass `tools=tools` to `AgenticApp()` when using tools with LLM
   - Guard LLM creation: `llm = Backend() if os.environ.get("KEY") else None`
4. Add E2E tests in `tests/e2e/test_examples.py`
5. Update `examples/README.md`

## Adding Authentication

1. Choose a scheme: `APIKeyHeader`, `APIKeyQuery`, `HTTPBearer`, or `HTTPBasic`
2. Write a verify function: `async (AuthCredentials) -> AuthUser | None`
3. Create `Authenticator(scheme=..., verify=...)`
4. Attach per-endpoint (`auth=`) or app-wide (`AgenticApp(auth=)`)
5. Access user in handler via `context.auth_user`
6. Reference: `examples/09_auth_agent/app.py`

## Adding File Upload/Download

### File Upload (multipart)

1. Add `UploadedFiles` type annotation to handler parameter
2. Client sends `multipart/form-data` with `intent` field and file fields
3. Files are injected as `dict[str, UploadFile]`

```python
from agenticapi import UploadedFiles

@app.agent_endpoint(name="documents")
async def handle(intent, context, files: UploadedFiles):
    pdf = files["document"]
    return {"filename": pdf.filename, "size": pdf.size, "type": pdf.content_type}
```

```bash
curl -X POST http://localhost:8000/agent/documents \
    -F 'intent=Analyze this document' \
    -F 'document=@report.pdf'
```

### File Download

1. Return `FileResult` from handler instead of a dict
2. Framework converts to the appropriate HTTP response (bytes, file path, or streaming)

```python
from agenticapi import FileResult

@app.agent_endpoint(name="export")
async def export_csv(intent, context):
    return FileResult(
        content=b"name,value\nalice,42",
        media_type="text/csv",
        filename="export.csv",
    )
```

Reference: `examples/10_file_handling/app.py`

## Adding Custom Response Types

Handlers can return non-JSON responses using result wrapper types:

```python
from agenticapi import HTMLResult, PlainTextResult, FileResult

# HTML page
@app.agent_endpoint(name="dashboard")
async def dashboard(intent, context):
    return HTMLResult(content="<h1>Dashboard</h1><p>Welcome!</p>")

# Plain text
@app.agent_endpoint(name="status")
async def status(intent, context):
    return PlainTextResult(content="OK")

# File download
@app.agent_endpoint(name="export")
async def export(intent, context):
    return FileResult(content=b"csv,data", media_type="text/csv", filename="export.csv")
```

You can also return any Starlette `Response` subclass directly (HTMLResponse, StreamingResponse, etc.) for full control over headers and status codes.

Reference: `examples/11_html_responses/app.py`

## Building HTMX Apps

AgenticAPI provides built-in HTMX support for building interactive server-rendered UIs with agent endpoints.

### HtmxHeaders (request detection)

Add `HtmxHeaders` as a handler parameter — it's auto-injected with parsed HTMX request headers:

```python
from agenticapi import HtmxHeaders, HTMLResult

@app.agent_endpoint(name="items")
async def items(intent, context, htmx: HtmxHeaders):
    if htmx.is_htmx:
        # Return just the HTML fragment for HTMX partial update
        return HTMLResult(content="<li>New item</li>")
    # Return full page for initial load
    return HTMLResult(content="<html>...</html>")
```

`HtmxHeaders` attributes: `is_htmx`, `boosted`, `target`, `trigger`, `trigger_name`, `current_url`, `prompt`

### htmx_response_headers (response control)

Use `htmx_response_headers()` to build HTMX response headers for client-side control:

```python
from agenticapi import htmx_response_headers, HTMLResult
from starlette.responses import HTMLResponse

@app.agent_endpoint(name="add")
async def add_item(intent, context, htmx: HtmxHeaders):
    # ... create item ...
    headers = htmx_response_headers(trigger="itemAdded", retarget="#item-list", reswap="beforeend")
    return HTMLResponse(content="<li>Added!</li>", headers=headers)
```

Supported headers: `trigger`, `trigger_after_settle`, `trigger_after_swap`, `redirect`, `refresh`, `retarget`, `reswap`, `push_url`, `replace_url`

Reference: `examples/12_htmx/app.py`

## Exposing Endpoints via MCP

1. Install: `pip install agenticapi[mcp]`
2. Mark endpoints: `@app.agent_endpoint(name="x", enable_mcp=True)`
3. Mount: `app.add_routes(expose_as_mcp(app))`
4. Only `enable_mcp=True` endpoints become MCP tools
5. Test: `npx @modelcontextprotocol/inspector http://localhost:8000/mcp`
6. Reference: `examples/08_mcp_agent/app.py`

## Creating a New Extension Package

Extensions are independently-installable packages under `extensions/<name>/` that wrap third-party libraries without bloating the core dependency graph.

High-level steps:

1. Create `extensions/<pkg-name>/` with its own `pyproject.toml`, `src/<pkg>/__init__.py`, `tests/conftest.py`, and `README.md`
2. Depend on `agenticapi>=0.1.0` and pin the wrapped library (`>=X.Y,<X.Y+1`)
3. Use **lazy imports** for the wrapped library (see `_imports.py` pattern in `agenticapi-claude-agent-sdk`)
4. Make all errors inherit from `agenticapi.AgenticAPIError`
5. Stub the wrapped library in `tests/conftest.py` so tests run offline
6. Ship `py.typed` in the package directory (PEP 561)
7. Document the public API in `README.md` and reference the extension from `development/extensions.md`

Full specification: see [development/extensions.md](extensions.md).

Reference implementation: `extensions/agenticapi-claude-agent-sdk/`
