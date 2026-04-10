# agenticapi-claude-agent-sdk

A Claude Agent SDK extension for [AgenticAPI](https://github.com/agenticapi/agenticapi).

This extension lets you run the **full Claude Agent SDK loop** —
planning, tool use, reflection, structured output — inside an
AgenticAPI agent endpoint, while preserving AgenticAPI's harness
guarantees: policy enforcement, audit trails, and tool registries.

It is **installed separately** from the main `agenticapi` package so
you only pay for it when you need it.

```bash
pip install agenticapi
pip install agenticapi-claude-agent-sdk
```

The extension declares `claude-agent-sdk >=0.1.58,<0.2` as a runtime
dependency and pulls it in for you. You will also need a Claude
authentication source — typically `ANTHROPIC_API_KEY`.

---

## Quick start

```python
from agenticapi import AgenticApp, CodePolicy
from agenticapi.runtime.tools.registry import ToolRegistry
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

`POST /agent/assistant {"intent": "..."}` will spin up a full Claude
Agent SDK session, stream the model's tool calls through the
permission adapter, and return the final answer wrapped in an
`AgentResponse`.

---

## What's in the box

| Public symbol | Purpose |
|---|---|
| `ClaudeAgentRunner` | High-level entry point. One call per request. Bridges policies + tool registry into the SDK |
| `ClaudeAgentSDKBackend` | `LLMBackend` adapter for one-shot text completions (drop-in replacement for `AnthropicBackend`) |
| `HarnessPermissionAdapter` | Standalone bridge from AgenticAPI policies to SDK `can_use_tool` + `PreToolUse` hooks |
| `build_sdk_mcp_server_from_registry` | Convert an AgenticAPI `ToolRegistry` into an in-process SDK MCP server |
| `sdk_tool_from_agenticapi_tool` | Convert a single `Tool` into an SDK MCP tool |
| `collect_session` / `stream_session_events` | Adapt a raw SDK message stream into an `AgentSessionResult` or a flat event stream |
| `ClaudeAgentSDKError` / `ClaudeAgentSDKNotInstalledError` / `ClaudeAgentSDKRunError` | Typed errors. All inherit from `agenticapi.AgenticAPIError` |

---

## When to use what

| Need | Use |
|---|---|
| Run the full agentic loop in an endpoint | `ClaudeAgentRunner` |
| Plug Claude into AgenticAPI's `IntentParser` or `CodeGenerator` | `ClaudeAgentSDKBackend` |
| Stream events to a UI or SSE endpoint | `ClaudeAgentRunner.stream(...)` |
| Reuse just the policy bridge (e.g. with your own SDK setup) | `HarnessPermissionAdapter` |
| Reuse just the tool bridge | `build_sdk_mcp_server_from_registry` |

The runner is **not** a replacement for `HarnessEngine`. It runs
*alongside* the harness as a peer execution strategy. Treat the
SDK loop as the model's "outer" planner and let AgenticAPI's
`CodeGenerator` + `ProcessSandbox` handle deterministic single-shot
work where you need a tighter sandbox.

---

## Permissions and safety

`ClaudeAgentRunner` installs two layers of defence around every tool
call:

1. **`can_use_tool` callback.** AgenticAPI policies are evaluated
   for every code-carrying tool (`Bash`, `Write`, `Edit`). If any
   policy denies, the call is rejected with `PermissionResultDeny`.

2. **`PreToolUse` hook.** Python source written via `Write`/`Edit`
   to `*.py` files is run through `check_code_safety()`, the same
   AST analyser AgenticAPI's harness uses for generated code. `Bash`
   commands are matched against a small list of obviously-harmful
   patterns (`rm -rf /`, `mkfs`, fork bombs, etc.).

Pass `deny_unknown_tools=True` for production endpoints to refuse
any tool that wasn't explicitly allow-listed.

> **Note.** The Claude Agent SDK runs in its own subprocess outside
> AgenticAPI's `ProcessSandbox`. The permission and hook layers are
> the *only* sandbox for tool calls executed via the SDK. Treat them
> as defence in depth, not as a kernel-level isolation boundary.

---

## Audit trails

Pass an `AuditRecorder` to record every session:

```python
from agenticapi.harness.audit.recorder import AuditRecorder

recorder = AuditRecorder()
runner = ClaudeAgentRunner(audit_recorder=recorder)
```

Each call to `runner.run()` produces an `ExecutionTrace` containing
the intent, the model's reasoning, every tool call, and every
permission decision the adapter made. See `examples/03_with_audit.py`
for a working endpoint that exposes the recorded traces.

---

## Authentication

The Claude Agent SDK reads its own environment variables. The
extension does not configure them — set them yourself before
starting the app:

```bash
export ANTHROPIC_API_KEY=sk-...
# or
export CLAUDE_CODE_USE_BEDROCK=1   # + AWS credentials
# or
export CLAUDE_CODE_USE_VERTEX=1    # + Google Cloud credentials
```

---

## Development

```bash
cd extensions/agenticapi-claude-agent-sdk
uv sync --extra dev          # install dev tools
uv run pytest                 # offline tests using a stubbed SDK
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
```

Tests do **not** require `claude-agent-sdk` to be installed —
`tests/conftest.py` installs a stub module that mimics the parts
of the SDK the extension uses.

---

## License

Apache 2.0, same as AgenticAPI itself.
