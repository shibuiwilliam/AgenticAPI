# Security Model

AgenticAPI implements defense-in-depth for safe agent code execution. Every piece of code an LLM generates passes through multiple safety layers before execution.

## Authentication

AgenticAPI provides HTTP authentication schemes following FastAPI's patterns:

### Security Schemes

| Scheme | What it extracts |
|---|---|
| `APIKeyHeader(name="X-API-Key")` | API key from a request header |
| `APIKeyQuery(name="api_key")` | API key from a query parameter |
| `HTTPBearer()` | Bearer token from `Authorization: Bearer <token>` |
| `HTTPBasic()` | Username/password from `Authorization: Basic <base64>` |

### Authenticator

Combines a scheme with a verify function:

```python
from agenticapi.security import APIKeyHeader, Authenticator, AuthUser

scheme = APIKeyHeader(name="X-API-Key")

async def verify(credentials):
    if credentials.credentials in VALID_KEYS:
        return AuthUser(user_id="u1", username="alice", roles=["admin"])
    return None  # -> AuthenticationError (401)

auth = Authenticator(scheme=scheme, verify=verify)

# Per-endpoint
@app.agent_endpoint(name="orders", auth=auth)

# Or app-wide default
app = AgenticApp(auth=auth)
```

### AuthUser

Available in handlers via `context.auth_user`:

```python
@app.agent_endpoint(name="orders", auth=auth)
async def handler(intent, context):
    user = context.auth_user  # AuthUser(user_id, username, roles, scopes, metadata)
    if "admin" not in user.roles:
        raise AuthorizationError("Admin role required")
```

## Layer 1: Prompt Design

User input is XML-escaped before inclusion in LLM prompts using `html.escape()` to prevent prompt injection attacks.

**Files:** `runtime/prompts/code_generation.py`, `runtime/prompts/intent_parsing.py`

## Layer 2: Static AST Analysis

Generated code is parsed into an AST and checked for dangerous patterns:

- **Forbidden imports**: configurable allow/deny lists, handles multi-line and submodule imports
- **eval/exec detection**: both direct calls (`eval()`) and attribute calls (`builtins.eval()`)
- **Dynamic imports**: `__import__()` via name or attribute access
- **Dangerous builtins**: `compile`, `globals`, `locals`, `vars`, `breakpoint`, `help`, `getattr`, `setattr`, `delattr`
- **File I/O**: `open()` via direct or attribute calls
- **Syntax errors**: code that can't be parsed is rejected

**File:** `harness/sandbox/static_analysis.py`

## Layer 3: Policy Evaluation

Four policy types evaluate generated code:

| Policy | What it checks |
|---|---|
| `CodePolicy` | Import allowlist/denylist, eval/exec, dynamic imports, network access, max lines |
| `DataPolicy` | SQL table/column access controls, DDL prevention, restricted columns (with quoted identifier support), result row limits |
| `ResourcePolicy` | Loop depth, large range() detection, recursion warnings |
| `RuntimePolicy` | AST node count (complexity), line count |

`DataPolicy` strips SQL comments (`--`, `/* */`) before write detection to prevent bypass.

## Layer 4: Approval Workflow

Write operations can require human approval:

```python
ApprovalWorkflow(rules=[
    ApprovalRule(
        name="write_gate",
        require_for_actions=["write", "execute"],
        approvers=["admin"],
        timeout_seconds=1800,
    ),
])
```

State transitions: `PENDING -> APPROVED | REJECTED | EXPIRED | ESCALATED`

Resolution uses `asyncio.Lock` to prevent race conditions on concurrent `resolve()` calls.

## Layer 5: Process Sandbox

- Code is **base64-encoded** for safe transport to the subprocess (no repr() injection)
- Execution in isolated subprocess via `asyncio.create_subprocess_exec` (no `shell=True`)
- Timeout enforcement with `asyncio.wait_for`
- Pre-populated namespace includes `data` dict with tool results (no direct tool access)
- Temp files cleaned up in `finally` block with null-safety guard

## Layer 6: Post-Execution Validation

- **ResourceMonitor**: checks CPU, memory, wall time against limits
- **OutputSizeMonitor**: rejects oversized output (default 1MB)
- **OutputTypeValidator**: ensures JSON-serializable results
- **ReadOnlyValidator**: warns if read intents produce write-like output

## Layer 7: Audit Trail

Every execution is recorded as an `ExecutionTrace` containing intent, generated code, policy evaluations, execution result, duration, and errors. `AuditRecorder` has bounded storage (`max_traces=10000`) to prevent memory exhaustion.

## File Upload Security

File uploads are accepted via `multipart/form-data` when a handler declares an `UploadedFiles` parameter. The `intent` field is extracted from the form data and processed through the normal intent pipeline.

- Uploaded files are held in memory as `bytes` — no temp files written to disk
- The `UploadFile` dataclass exposes `filename`, `content_type`, `content`, and `size`
- File content is **not** passed to the LLM or sandbox — handlers process files directly
- There is no built-in file size limit; application-level validation should be added in handlers
- `python-multipart` dependency handles multipart parsing

## MCP Security

When exposing endpoints via MCP (`enable_mcp=True`), the same harness pipeline applies — MCP tool calls go through intent parsing, policy evaluation, and sandbox execution. Only explicitly opted-in endpoints are exposed.

## Known Limitations (Phase 1)

- `ProcessSandbox` provides process-level isolation, not kernel-level (ContainerSandbox is Phase 2)
- AST analysis detects known patterns; sophisticated obfuscation may bypass it
- Sessions, audit traces, and approval requests are in-memory (not persistent)
- API keys must be provided via environment variables, never hardcoded
- MCP transport does not yet support authentication/authorization
- Approval resolution is programmatic only (no built-in admin HTTP endpoint)
- File uploads have no built-in size limit — enforce in handler logic
