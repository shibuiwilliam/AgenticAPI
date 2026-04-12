# Extensions Architecture

AgenticAPI supports independently-installable **extension packages** that wrap third-party libraries (LLM SDKs, framework adapters, domain-specific runtimes) without bloating the core package.

## Why a separate-package layout?

The core `agenticapi` package is deliberately narrow: Starlette, Pydantic, structlog, httpx, and the three supported LLM vendor SDKs. Anything else — especially large or fast-moving dependencies — lives in an extension package under `extensions/<name>/`.

Reasons:

1. **Dependency weight.** Core users shouldn't pay disk/install cost for libraries they don't need. The Claude Agent SDK, for example, is 40+ MB with its own subprocess runtime.
2. **Version drift.** Fast-moving SDKs (e.g., `claude-agent-sdk>=0.1.58,<0.2`) would force churn in the core package's release cadence. Isolating them to extensions lets each extension pin independently.
3. **Surface area.** Each extension owns its own public API, exceptions, tests, and docs. Breaking changes in an extension don't affect core users.
4. **Security review.** Smaller core = smaller audit surface for the harness/policy code that matters most.

The extras mechanism (`[project.optional-dependencies]`) is **not** used for this purpose. `agenticapi[claude-agent-sdk]` would still pull the SDK into core's dependency graph; a separate package keeps it fully decoupled.

---

## Directory Layout

```
extensions/
    <extension-name>/
        pyproject.toml               # Own build system, own version
        README.md                    # User-facing docs
        src/
            <package_name>/
                __init__.py          # Public API via __all__
                py.typed             # PEP 561 marker
                _imports.py          # Lazy import shim (if wrapping an optional dep)
                exceptions.py        # Error types inheriting from AgenticAPIError
                <feature>.py         # Implementation modules
        tests/
            conftest.py              # Stub optional deps for offline testing
            test_*.py
        examples/
            NN_example.py            # Runnable scripts
            README.md
```

The package inside `src/` uses **underscored** names (Python module convention), while the distribution name on PyPI uses **hyphens** (PEP 503). Example: distribution `agenticapi-claude-agent-sdk` → import `agenticapi_claude_agent_sdk`.

---

## Required Conventions

### 1. Dependency pinning

Depend on core and the wrapped library with explicit bounds:

```toml
dependencies = [
    "agenticapi>=0.1.0",
    "claude-agent-sdk>=0.1.58,<0.2",   # Pin upper bound for fast-moving deps
    "structlog>=25.5.0",
]
```

Upper bounds prevent unexpected breaks when the wrapped library ships a major version.

### 2. Lazy imports

The extension must `import` successfully even when the wrapped library is missing. Use a lazy-import shim:

```python
# _imports.py
from __future__ import annotations

from typing import Any

from agenticapi_claude_agent_sdk.exceptions import ClaudeAgentSDKNotInstalledError


def load_sdk() -> Any:
    """Import claude_agent_sdk, raising a friendly error if missing."""
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise ClaudeAgentSDKNotInstalledError(
            "claude-agent-sdk is not installed. "
            "Run: pip install claude-agent-sdk"
        ) from exc
    return claude_agent_sdk
```

Call `load_sdk()` only inside the function that actually needs it (e.g., `ClaudeAgentRunner.run()`, not module-level).

### 3. Exception hierarchy

All extension errors must inherit from `agenticapi.AgenticAPIError` so callers can catch core + extension errors uniformly:

```python
from agenticapi import AgenticAPIError


class ClaudeAgentSDKError(AgenticAPIError):
    """Base class for all Claude Agent SDK extension errors."""


class ClaudeAgentSDKNotInstalledError(ClaudeAgentSDKError):
    """Raised when claude-agent-sdk is not importable."""


class ClaudeAgentSDKRunError(ClaudeAgentSDKError):
    """Raised when a session ended with a non-success result."""
```

### 4. Offline tests

Tests MUST run without the wrapped library installed. Install a stub module in `conftest.py`:

```python
# tests/conftest.py
import sys
import types

# Build a stub that mimics only the SDK surface the extension uses.
_stub = types.ModuleType("claude_agent_sdk")
_stub.query = ...         # fake implementation
_stub.ClaudeAgentOptions = ...
sys.modules["claude_agent_sdk"] = _stub
```

This keeps the test suite deterministic, network-free, and fast. Real SDK integration is verified out-of-band (e.g., in a separate nightly job).

### 5. Type checking

Each extension runs its own strict mypy configuration. Add an override for the wrapped library if it lacks type stubs:

```toml
[[tool.mypy.overrides]]
module = "claude_agent_sdk.*"
ignore_missing_imports = true
```

### 6. PEP 561 marker

Ship `py.typed` in the package directory so downstream mypy users pick up the inline types:

```
src/<package>/py.typed
```

List it in `pyproject.toml` if your build backend needs it declared explicitly.

---

## Public API Rules

- **Everything public goes through the top-level `__init__.py`.** Submodules should be treated as internal — users import from `agenticapi_<ext>`, not `agenticapi_<ext>.submodule`.
- **`__all__` is mandatory.** It's the single source of truth for what's exported. CI can diff it against the documented surface.
- **No transitive re-exports from core.** Don't re-export `AgenticApp` or `Intent` from an extension — users import core types from `agenticapi`.
- **Version matches the package.** Export `__version__ = "x.y.z"` from `__init__.py`.

---

## Installation Patterns

### End users

```bash
pip install agenticapi                          # Core
pip install agenticapi-claude-agent-sdk         # Add extension (pulls its deps)
```

Extensions should never be required for core to work. Handlers that need an extension either import it explicitly at module load, or guard the import behind a runtime check.

### Contributors

From the monorepo root:

```bash
# Install core in editable mode (already done by uv sync)
uv sync --group dev

# Install the extension editable, linked against local core
uv pip install -e extensions/agenticapi-claude-agent-sdk --no-deps

# Run the extension's tests via the root venv
uv run pytest extensions/agenticapi-claude-agent-sdk/tests

# Type-check
uv run mypy extensions/agenticapi-claude-agent-sdk/src
```

`--no-deps` is important: it prevents `uv pip` from pulling `agenticapi` from PyPI and clobbering your editable checkout.

---

## Integration Patterns

Extensions typically integrate with one or more core subsystems:

| Core subsystem | How to integrate |
|---|---|
| `LLMBackend` protocol | Implement `generate()`, `generate_stream()`, `model_name` — drop-in replacement for built-in backends |
| `Tool` protocol | Implement `definition` property and `invoke()` — register in `ToolRegistry` |
| `Policy` base class | Subclass, implement `evaluate()` — add to `HarnessEngine(policies=...)` |
| `AuditRecorder` | Accept a recorder in the extension's constructor; record `ExecutionTrace` on significant events |
| `AgentResponse` | Return an `AgentResponse` from handlers so the framework serializes it uniformly |
| `AgentContext` | Read `context.session_id`, `context.auth_user`, `context.metadata` to participate in the request lifecycle |

An extension is not obligated to touch all of these. The minimum viable extension is a single class or function that takes `Intent` + `AgentContext` and returns an `AgentResponse`.

---

## Reference Extension: `agenticapi-claude-agent-sdk`

The `agenticapi-claude-agent-sdk` package is the canonical example. It demonstrates every convention above.

**Layout:**

```
extensions/agenticapi-claude-agent-sdk/
    pyproject.toml                 # Depends on agenticapi + claude-agent-sdk
    README.md
    src/agenticapi_claude_agent_sdk/
        __init__.py                # Exports 15 public symbols via __all__
        py.typed
        _imports.py                # Lazy SDK loader
        exceptions.py              # 3 error types, all inherit AgenticAPIError
        backend.py                 # ClaudeAgentSDKBackend (LLMBackend adapter)
        runner.py                  # ClaudeAgentRunner (full agentic loop)
        tools.py                   # Tool registry → SDK MCP server bridge
        permissions.py             # Policy → SDK can_use_tool + PreToolUse bridge
        messages.py                # SDK message stream → AgentResponse collector
        options.py                 # ClaudeAgentOptions builder
    tests/
        conftest.py                # Stub claude_agent_sdk module (~300 lines)
        test_imports.py            # Import shim behaviour
        test_backend.py            # Text completion + streaming
        test_runner.py             # Full session orchestration
        test_tools.py              # Tool bridge
        test_permissions.py        # Policy + hook enforcement
        test_messages.py           # Collector + event stream
    examples/
        01_simple_query.py         # Minimal ClaudeAgentRunner
        02_with_agenticapi_tools.py  # Tool registry + policies
        03_with_audit.py           # AuditRecorder integration
        README.md
```

**Public API (`__all__`, 15 items):**

| Symbol | Kind | Purpose |
|---|---|---|
| `ClaudeAgentRunner` | class | High-level orchestrator; one call per request |
| `ClaudeAgentSDKBackend` | class | `LLMBackend` adapter for intent parser / code generator |
| `HarnessPermissionAdapter` | class | Policy → SDK permission bridge (standalone) |
| `AgentSessionResult` | dataclass | Aggregated SDK session output |
| `AgentSessionEvent` | dataclass | Flat event for streaming (SSE/websocket) |
| `ToolCallRecord` | dataclass | Single tool invocation record |
| `PermissionDecision` | dataclass | Audit record for a permission check |
| `build_claude_agent_options` | function | Build `ClaudeAgentOptions` with policy + tool wiring |
| `build_sdk_mcp_server_from_registry` | function | `ToolRegistry` → in-process SDK MCP server |
| `sdk_tool_from_agenticapi_tool` | function | Single `Tool` → SDK MCP tool |
| `collect_session` | async function | Drain SDK message stream into `AgentSessionResult` |
| `stream_session_events` | async generator | Adapt message stream to flat `AgentSessionEvent` stream |
| `ClaudeAgentSDKError` | exception | Base error |
| `ClaudeAgentSDKNotInstalledError` | exception | SDK not importable |
| `ClaudeAgentSDKRunError` | exception | Session ended with error |
| `__version__` | str | `"0.1.0"` |

**Safety layers for SDK tool calls:**

The Claude Agent SDK runs tool calls inside its own subprocess, outside AgenticAPI's `ProcessSandbox`. The extension adds two layers of defense:

1. **`can_use_tool` callback** — Evaluates AgenticAPI policies on every `Write`, `Edit`, or `Bash` tool call. Returns `PermissionResultDeny` on policy violation.
2. **`PreToolUse` hook** — Runs AST static analysis (`check_code_safety()`) on Python payloads written to `*.py` files, and matches shell commands against a denylist of obvious harmful patterns (`rm -rf /`, `mkfs`, fork bombs).

These are defense in depth, **not** kernel-level isolation. See the extension's README for the full threat model.

**Related docs:**

- [claude-agent-sdk-extension-plan.md](claude-agent-sdk-extension-plan.md) — Design rationale and API surface
- `extensions/agenticapi-claude-agent-sdk/README.md` (at repo root) — User-facing quickstart

---

## CI & Release

Each extension ships independently:

- **Own version.** `extensions/<name>/pyproject.toml` holds its own `version = "x.y.z"`.
- **Own tests.** The CI workflow should run extension tests in a separate job so failures don't block core releases.
- **Own changelog.** Keep a `CHANGELOG.md` inside `extensions/<name>/` if you cut releases.
- **PyPI publication.** Build and upload from `extensions/<name>/` — the `hatchling` backend handles it:
  ```bash
  cd extensions/<name>
  uv build
  uv publish
  ```

The root `.github/workflows/ci.yml` does not yet run extension tests automatically. This is tracked as a follow-up.

---

## Adding a New Extension — Checklist

1. [ ] Create `extensions/<pkg-name>/` with layout above
2. [ ] `pyproject.toml` with pinned dependency bounds and strict ruff/mypy config
3. [ ] `src/<pkg>/__init__.py` with `__all__` and `__version__`
4. [ ] `src/<pkg>/py.typed` marker
5. [ ] Lazy `_imports.py` shim if wrapping an optional dep
6. [ ] `exceptions.py` with errors inheriting from `AgenticAPIError`
7. [ ] `tests/conftest.py` stubbing the wrapped library for offline tests
8. [ ] `README.md` with quickstart, public API table, safety notes
9. [ ] `examples/` with runnable scripts
10. [ ] Reference in `extensions.md` under "Reference Extensions"
11. [ ] Note in root `CLAUDE.md` (at repo root) Extensions table
