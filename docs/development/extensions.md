# Extensions

AgenticAPI keeps its core minimal and ships heavyweight or fast-moving integrations as **separate, independently-versioned packages** under `extensions/<name>/`. Each extension has its own `pyproject.toml`, its own dependency tree, and its own release cycle, but reuses AgenticAPI's public API surface.

This avoids polluting the core `agenticapi` package with optional heavyweight dependencies while still keeping integrations close to the framework.

## Why separate packages?

Large or fast-moving dependencies (LLM SDKs, vector databases, full agentic frameworks) don't belong in `pyproject.toml` extras of the core package. They are released as their own PyPI packages following the naming pattern `agenticapi-<name>`.

| Approach | Used for |
|---|---|
| **Core dependency** | Always required (Starlette, Pydantic, structlog, httpx) |
| **Optional extra** (`agenticapi[mcp]`) | Lightweight, stable optional features |
| **Separate extension package** | Heavyweight/fast-moving integrations (Claude Agent SDK, vector DBs, etc.) |

## Available Extensions

### agenticapi-claude-agent-sdk

Run the **full Claude Agent SDK loop** (planning, tool use, reflection, structured output) inside an AgenticAPI agent endpoint, while preserving AgenticAPI's harness guarantees: policy enforcement, audit trails, and tool registries.

**Install:**

```bash
pip install agenticapi
pip install agenticapi-claude-agent-sdk
```

**Quick start:**

```python
from agenticapi import AgenticApp, CodePolicy
from agenticapi_claude_agent_sdk import ClaudeAgentRunner

app = AgenticApp(title="my-service")

runner = ClaudeAgentRunner(
    system_prompt="You are a coding assistant.",
    allowed_tools=["Read", "Glob", "Grep"],
    policies=[CodePolicy(denied_modules=["os", "subprocess"])],
)

@app.agent_endpoint(name="assistant", autonomy_level="manual")
async def assistant(intent, context):
    return await runner.run(intent=intent, context=context)
```

**What's in the box:**

| Public symbol | Purpose |
|---|---|
| `ClaudeAgentRunner` | High-level entry point — bridges policies + tool registry into the SDK |
| `ClaudeAgentSDKBackend` | `LLMBackend` adapter — drop-in replacement for `AnthropicBackend` |
| `HarnessPermissionAdapter` | Bridge from AgenticAPI policies to SDK `can_use_tool` + `PreToolUse` hooks |
| `build_sdk_mcp_server_from_registry` | Convert an AgenticAPI `ToolRegistry` into an in-process SDK MCP server |
| `sdk_tool_from_agenticapi_tool` | Convert a single `Tool` into an SDK MCP tool |
| `collect_session` / `stream_session_events` | Adapt raw SDK message stream into `AgentSessionResult` or flat event stream |

**Permissions and safety.** `ClaudeAgentRunner` installs two layers of defence around every tool call:

1. **`can_use_tool` callback** — AgenticAPI policies are evaluated for every code-carrying tool. Denied calls return `PermissionResultDeny`.
2. **`PreToolUse` hook** — Python source written via `Write`/`Edit` to `*.py` files runs through `check_code_safety()`, the same AST analyser the harness uses. `Bash` commands are matched against obviously-harmful patterns.

The Claude Agent SDK runs in its own subprocess outside AgenticAPI's `ProcessSandbox`. The permission and hook layers are the only sandbox for tool calls executed via the SDK — treat them as defence in depth.

**Audit trails.** Pass an `AuditRecorder` to record every session:

```python
from agenticapi.harness.audit.recorder import AuditRecorder

recorder = AuditRecorder()
runner = ClaudeAgentRunner(audit_recorder=recorder)
```

Each call produces an `ExecutionTrace` with the intent, model reasoning, every tool call, and every permission decision.

**Authentication.** The Claude Agent SDK reads its own environment variables. Set them yourself:

```bash
export ANTHROPIC_API_KEY=sk-...
# or for Bedrock:
export CLAUDE_CODE_USE_BEDROCK=1
# or for Vertex:
export CLAUDE_CODE_USE_VERTEX=1
```

**Source:** [`extensions/agenticapi-claude-agent-sdk/`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/extensions/agenticapi-claude-agent-sdk)

---

## Building a New Extension

To create an extension, follow this structure:

```
extensions/agenticapi-<name>/
    pyproject.toml         # Independent package metadata
    README.md              # User-facing docs
    src/
        agenticapi_<name>/
            __init__.py    # Public API
            ...
    tests/
        conftest.py        # Stub SDK if needed for offline tests
        test_*.py
    examples/              # Working endpoint examples
```

### Naming convention

- Directory: `extensions/agenticapi-<short-name>/`
- PyPI package: `agenticapi-<short-name>` (kebab-case)
- Python package: `agenticapi_<short_name>` (snake_case)

### `pyproject.toml` requirements

```toml
[project]
name = "agenticapi-<name>"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "agenticapi>=0.1.0",
    "<heavy-dep>>=X.Y",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/agenticapi_<name>"]
```

### Guidelines

1. **Reuse, don't fork.** Import from `agenticapi.*` for all base types — never duplicate `Policy`, `Tool`, `LLMBackend`, etc.
2. **Inherit AgenticAPI exceptions.** All custom errors should subclass `agenticapi.AgenticAPIError`.
3. **Use the same tooling.** ruff format (line length 120), mypy strict, Google docstrings.
4. **Offline tests.** Tests should not require the heavyweight dependency to be installed — provide a stub in `tests/conftest.py` (see `agenticapi-claude-agent-sdk/tests/conftest.py` for an example).
5. **Self-contained README.** Document install, quick start, public API, safety considerations, and authentication.

### Development workflow

```bash
cd extensions/agenticapi-<name>
uv sync --extra dev          # install dev tools
uv run pytest                 # offline tests using stubs
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
```

Each extension is its own Python project — its tests, lints, and type checks run independently from the main `agenticapi` package.
