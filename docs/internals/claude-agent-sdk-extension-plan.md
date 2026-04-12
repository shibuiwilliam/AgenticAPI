# Claude Agent SDK Extension — Implementation Plan

**Status:** Approved (Phase 1 — initial release)
**Target version:** `agenticapi-claude-agent-sdk` v0.1.0
**Owner:** Core team
**Author:** Implementation plan generated 2026-04-10

---

## 1. Goals

Build an **independently-installable extension package** that integrates the
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) into
AgenticAPI. The extension turns the SDK's full agentic loop (planning →
tool use → reflection → final answer) into a first-class AgenticAPI execution
strategy, while preserving AgenticAPI's harness guarantees: policy enforcement,
audit trails, approval workflows, and tool registries.

### What success looks like

A user can:

```bash
pip install agenticapi
pip install agenticapi-claude-agent-sdk
```

```python
from agenticapi import AgenticApp, CodePolicy
from agenticapi_claude_agent_sdk import ClaudeAgentRunner, ClaudeAgentSDKBackend

app = AgenticApp(title="claude-sdk-demo")
runner = ClaudeAgentRunner(
    system_prompt="You are a helpful coding assistant.",
    allowed_tools=["Read", "Glob", "Grep"],
    policies=[CodePolicy(denied_modules=["os", "subprocess"])],
)

@app.agent_endpoint(name="assistant", autonomy_level="manual")
async def assistant(intent, context):
    return await runner.run(intent=intent, context=context)
```

…and that single endpoint will run a full Claude Agent SDK session, with
AgenticAPI policies bridged into Claude's permission/hook system, and the
result wrapped into an `AgentResponse` with execution trace recorded.

### Non-goals (this iteration)

- Replacing AgenticAPI's `LLMBackend` for the harness's code-generation path.
  The SDK runs whole agent loops, not single-shot code generation, so wiring
  it into `HarnessEngine.execute()` would force a leaky abstraction. We expose
  it as a *parallel* execution path, not a substitute for `CodeGenerator`.
- Multi-turn conversational state via `ClaudeSDKClient`. We use the simpler
  `query()` one-shot interface in v0.1; multi-turn comes in v0.2.
- Subagent support (`agents=`) — listed as a v0.2 follow-up.

---

## 2. Why a separate package (not `agenticapi[claude-sdk]`)

| Concern | Optional extra | Separate package |
|---|---|---|
| Install size | `claude-agent-sdk` is ~56 MB; users not using it pay nothing | Same (only installed if requested) |
| Versioning | Locked to AgenticAPI release cycle | Can iterate independently as the SDK evolves |
| Coupling | Risk of importing SDK types into core | Hard boundary via published API |
| Discoverability | Hidden behind `[extras]` syntax | First-class on PyPI |
| Precedent | `agenticapi[mcp]` (small, stable dep) | Better fit for large, fast-moving deps |

We pick **separate package**. The Claude Agent SDK is large and evolving; an
independent package lets us follow it without forcing AgenticAPI releases.

### Layout in this repo

```
extensions/
  agenticapi-claude-agent-sdk/
    pyproject.toml             # Independent package metadata
    README.md
    LICENSE                    # Inherits Apache-2.0
    src/agenticapi_claude_agent_sdk/
      __init__.py              # Public API surface
      _imports.py              # Lazy-import shim with friendly errors
      backend.py               # ClaudeAgentSDKBackend (LLMBackend protocol)
      runner.py                # ClaudeAgentRunner (high-level entry point)
      tools.py                 # Tool bridge (AgenticAPI Tool → SDK MCP tool)
      permissions.py           # Policy → can_use_tool + hooks bridge
      messages.py              # SDK message → AgentResponse adapter
      options.py               # ClaudeAgentOptions builder helpers
      exceptions.py            # ClaudeAgentSDKError + subclasses
      types.py                 # Re-exported types and small dataclasses
    tests/
      __init__.py
      conftest.py              # Stub claude_agent_sdk for offline tests
      test_backend.py
      test_runner.py
      test_tools.py
      test_permissions.py
      test_messages.py
    examples/
      01_simple_query.py
      02_with_agenticapi_tools.py
      03_with_policies.py
      README.md
```

---

## 3. Architecture

### 3.1 Component diagram

```
                ┌────────────────────────────────────────────┐
                │            AgenticAPI app code             │
                └──────────────┬─────────────────────────────┘
                               │  intent, context
                               ▼
                ┌────────────────────────────────────────────┐
                │           ClaudeAgentRunner                │
                │  (the high-level orchestrator)             │
                └──────┬──────┬──────┬──────┬────────────────┘
                       │      │      │      │
        ┌──────────────┘      │      │      └──────────────────┐
        ▼                     ▼      ▼                         ▼
┌───────────────┐    ┌────────────┐ ┌──────────────┐  ┌────────────────┐
│ Tool bridge   │    │ Permission │ │ Options      │  │ Message        │
│ (AgenticAPI   │    │ adapter    │ │ builder      │  │ adapter        │
│  Tool → SDK   │    │ (Policies →│ │              │  │ (SDK msgs →    │
│  MCP tool)    │    │  hooks +   │ │              │  │  AgentResponse)│
│               │    │  can_use)  │ │              │  │                │
└──────┬────────┘    └──────┬─────┘ └──────┬───────┘  └────────┬───────┘
       │                    │              │                    │
       └────────────────────┴──────┬───────┴────────────────────┘
                                   ▼
                ┌────────────────────────────────────────────┐
                │  claude_agent_sdk.query(prompt, options)   │
                └────────────────────────────────────────────┘
```

### 3.2 Execution flow

1. `runner.run(intent, context)` is called.
2. Runner builds an `ClaudeAgentOptions` via the **options builder** that:
   - merges built-in SDK tools (`allowed_tools`) with the AgenticAPI tool bridge,
   - installs a `can_use_tool` callback derived from AgenticAPI policies,
   - installs a `PreToolUse` hook for static analysis on `Bash`/`Write`/`Edit`,
   - installs a `PostToolUse` hook to mirror tool calls into the audit trace,
   - sets `cwd`, `env`, `model`, `permission_mode`, `max_turns`, `system_prompt`.
3. Runner calls `claude_agent_sdk.query(prompt=intent.raw, options=...)` and
   iterates the async stream of messages.
4. The **message adapter** collects `AssistantMessage` content blocks, builds
   a `tool_calls` list from `ToolUseBlock`s, captures the final `ResultMessage`,
   and produces an `AgentResponse` with:
   - `result` = `ResultMessage.result` (or `structured_output` if set),
   - `reasoning` = concatenated `ThinkingBlock` text,
   - `generated_code` = collected `Bash`/`Write` tool input snippets,
   - `confidence` = derived from `is_error` / `subtype`,
   - `execution_trace_id` = recorded via `HarnessEngine.audit_recorder` if a
     harness is supplied.
5. Optional: when an `audit_recorder` is configured, the runner records a
   complete `ExecutionTrace` for the SDK session.

### 3.3 Key design choices and trade-offs

| Decision | Rationale |
|---|---|
| Use `query()` (one-shot) not `ClaudeSDKClient` | Maps cleanly to one HTTP request → one agent invocation; no session state to manage; trivially cancellable |
| Lazy-import the SDK | Tests and `import agenticapi_claude_agent_sdk` succeed even when the SDK isn't installed; only `ClaudeAgentRunner.run()` requires it |
| Bridge AgenticAPI policies via `can_use_tool` AND a `PreToolUse` hook | `can_use_tool` is the documented permission gate, but hooks fire even in `bypassPermissions` mode and can mutate input — defence in depth |
| Wrap AgenticAPI `Tool` instances as SDK MCP tools via `create_sdk_mcp_server` | In-process, no subprocess, no JSON-RPC — minimal overhead and no extra deps |
| Run static analysis on `Bash`/`Write`/`Edit` inputs in the hook | Prevents the SDK from running shell commands that AgenticAPI's `CodePolicy.denied_modules` would forbid in generated Python |
| Don't try to make the SDK a `LLMBackend` for `HarnessEngine` | Single-shot and full-loop are different abstractions. Forcing them to share an interface would muddy both. The runner is a peer, not a replacement |

---

## 4. Public API (v0.1)

```python
# extensions/agenticapi-claude-agent-sdk/src/agenticapi_claude_agent_sdk/__init__.py

from agenticapi_claude_agent_sdk.backend import ClaudeAgentSDKBackend
from agenticapi_claude_agent_sdk.exceptions import (
    ClaudeAgentSDKError,
    ClaudeAgentSDKNotInstalledError,
    ClaudeAgentSDKRunError,
)
from agenticapi_claude_agent_sdk.messages import AgentSessionResult
from agenticapi_claude_agent_sdk.permissions import HarnessPermissionAdapter
from agenticapi_claude_agent_sdk.runner import ClaudeAgentRunner
from agenticapi_claude_agent_sdk.tools import (
    build_sdk_mcp_server_from_registry,
    sdk_tool_from_agenticapi_tool,
)

__version__ = "0.1.0"
__all__ = [
    "AgentSessionResult",
    "ClaudeAgentRunner",
    "ClaudeAgentSDKBackend",
    "ClaudeAgentSDKError",
    "ClaudeAgentSDKNotInstalledError",
    "ClaudeAgentSDKRunError",
    "HarnessPermissionAdapter",
    "__version__",
    "build_sdk_mcp_server_from_registry",
    "sdk_tool_from_agenticapi_tool",
]
```

### Class signatures

```python
class ClaudeAgentRunner:
    def __init__(
        self,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        allowed_tools: Sequence[str] = (),
        disallowed_tools: Sequence[str] = (),
        permission_mode: str = "default",
        max_turns: int | None = None,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        tool_registry: ToolRegistry | None = None,
        policies: Sequence[Policy] = (),
        audit_recorder: AuditRecorder | None = None,
        approval_workflow: ApprovalWorkflow | None = None,
        extra_options: Mapping[str, Any] | None = None,
        mcp_server_name: str = "agenticapi",
    ) -> None: ...

    async def run(
        self,
        *,
        intent: Intent,
        context: AgentContext,
    ) -> AgentResponse: ...

    async def stream(
        self,
        *,
        intent: Intent,
        context: AgentContext,
    ) -> AsyncIterator[AgentSessionEvent]: ...


class ClaudeAgentSDKBackend:
    """LLMBackend protocol implementation for one-shot text completion.

    Wraps query() so the SDK can be used wherever AgenticAPI expects an
    LLMBackend (intent parsing, code generation). Does NOT expose the full
    agent loop — for that, use ClaudeAgentRunner.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        permission_mode: str = "bypassPermissions",  # text-only mode
        extra_options: Mapping[str, Any] | None = None,
    ) -> None: ...

    async def generate(self, prompt: LLMPrompt) -> LLMResponse: ...
    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]: ...

    @property
    def model_name(self) -> str: ...
```

---

## 5. Implementation priorities

Implementation is split into phases. Each phase is independently shippable.

### Phase A — minimum viable extension (this iteration)

1. **Lazy import shim** (`_imports.py`) — friendly error if SDK not installed.
2. **Tool bridge** (`tools.py`) — convert `Tool` → `SdkMcpTool`, build MCP server.
3. **Permission adapter** (`permissions.py`) — `can_use_tool` + `PreToolUse` hook
   wired to `PolicyEvaluator` and `check_code_safety`.
4. **Message adapter** (`messages.py`) — collect SDK stream → `AgentSessionResult`.
5. **Options builder** (`options.py`) — assemble `ClaudeAgentOptions`.
6. **Runner** (`runner.py`) — high-level `run()` returning `AgentResponse`.
7. **LLM backend** (`backend.py`) — thin wrapper for one-shot use.
8. **Tests** — offline tests using a stubbed `claude_agent_sdk` module.
9. **Example** — `01_simple_query.py` and `02_with_agenticapi_tools.py`.
10. **README** — install, usage, links to AgenticAPI docs.

### Phase B — follow-up (v0.2)

- `ClaudeSDKClient`-backed multi-turn `ClaudeAgentSession` class.
- Subagent support (`agents=`).
- Approval workflow integration (raise `ApprovalRequired` from a hook).
- Streaming `AgentResponse` via Starlette `StreamingResponse`.
- More example apps; e2e test against the real SDK in CI (gated by env var).

### Phase C — production polish (v0.3+)

- OpenTelemetry spans around each tool call.
- Cost accounting from `ResultMessage.total_cost_usd` into AgenticAPI's audit.
- Custom permission UI integration.
- Retry/backoff on `RateLimitEvent`.

---

## 6. Test strategy

The Claude Agent SDK requires the Claude CLI binary and (optionally) network
access to Anthropic. We do **not** make those mandatory for AgenticAPI's CI.

- **Unit tests** stub `claude_agent_sdk` with a fake module fixture
  (`conftest.py`) that emits a deterministic message stream. This covers:
  - `ClaudeAgentRunner.run()` happy path,
  - permission denial via `can_use_tool` returning `PermissionResultDeny`,
  - hook-based static analysis blocking a `Bash` `rm -rf /` call,
  - tool bridge converting an AgenticAPI `Tool` and invoking it,
  - error mapping (CLI not found → `ClaudeAgentSDKNotInstalledError`).
- **Integration tests** (gated by `RUN_CLAUDE_SDK_INTEGRATION=1` and
  `ANTHROPIC_API_KEY`) run against the real SDK. Skipped by default.

Coverage goal: **≥ 90 %** for the extension's `src/`.

---

## 7. Quality gates

Mirrors AgenticAPI's CI requirements:

```bash
uv run ruff format --check extensions/agenticapi-claude-agent-sdk/
uv run ruff check extensions/agenticapi-claude-agent-sdk/
uv run mypy extensions/agenticapi-claude-agent-sdk/src
uv run pytest extensions/agenticapi-claude-agent-sdk/tests
```

The extension's `pyproject.toml` declares `agenticapi >=0.1.0` and
`claude-agent-sdk >=0.1.58` as runtime dependencies, plus a `[dev]` extra
mirroring the main repo's tooling versions.

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Claude Agent SDK API changes | Public types are imported lazily and pinned via `>=0.1.58,<0.2`; we re-pin per release with a smoke test |
| Users confused about runner vs harness | README has a clear "when to use what" section; the runner accepts an optional `audit_recorder` so users can still capture traces |
| Policy bridge gaps (SDK has tools we don't model) | Default to **deny** in `can_use_tool` for unmodelled tool names when policies are present |
| `Bash` tool bypassing AgenticAPI policies | The `PreToolUse` hook on `Bash` parses the command and rejects denied modules / shell builtins; documented as best-effort, not a kernel sandbox |
| Subprocess invocation overhead | Documented; Phase B will offer a long-lived `ClaudeAgentSession` reusing one CLI process |

---

## 9. Out of scope (and why)

- **Replacing the harness's code generator with the SDK.** Different shapes
  (loop vs single shot). Forcing them together would invent a third interface
  that fits neither.
- **Container/VM sandboxing of the SDK process.** AgenticAPI's `ProcessSandbox`
  isolates its own subprocess; the SDK starts its own CLI process which is out
  of our isolation boundary. We document this; container isolation is a
  Phase 2 topic for the AgenticAPI core (`harness/sandbox/container.py`).
- **A custom CLI for the extension.** The runner is a library, used from a
  user's `AgenticApp`. No new CLI surface.
