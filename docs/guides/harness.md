# Harness & Safety

The harness system is AgenticAPI's core safety layer. Every piece of LLM-generated code passes through a multi-stage pipeline before execution.

## Pipeline

```
Generated Code
  -> Policy Evaluation    (CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy)
  -> Static AST Analysis  (check_code_safety)
  -> Approval Check       (ApprovalWorkflow, if configured)
  -> Sandbox Execution    (ProcessSandbox)
  -> Post-Execution Monitors (ResourceMonitor, OutputSizeMonitor)
  -> Post-Execution Validators (OutputTypeValidator, ReadOnlyValidator)
  -> Audit Recording      (AuditRecorder + ExecutionTrace)
```

## HarnessEngine

```python
from agenticapi import HarnessEngine, CodePolicy, DataPolicy

harness = HarnessEngine(
    policies=[
        CodePolicy(denied_modules=["os", "subprocess"]),
        DataPolicy(deny_ddl=True),
    ],
)
```

See [Policies](../api/policies.md), [Approval](approval.md), and [Security](security.md) for details on each stage.

## Four Policy Types

### CodePolicy

Controls what Python constructs are allowed in generated code:

```python
CodePolicy(
    denied_modules=["os", "subprocess", "sys", "shutil"],  # Blocked imports
    deny_eval_exec=True,       # No eval() or exec()
    deny_dynamic_import=True,  # No __import__()
    allow_network=False,       # No socket/urllib/requests
    max_code_lines=500,        # Max generated code size
)
```

### DataPolicy

Controls SQL data access patterns:

```python
DataPolicy(
    readable_tables=["orders", "products"],
    writable_tables=["orders", "cart"],
    restricted_columns=["password_hash", "ssn"],
    deny_ddl=True,
    max_result_rows=1000,
)
```

### ResourcePolicy

Limits computational resources:

```python
ResourcePolicy(
    max_cpu_seconds=30,
    max_memory_mb=512,
    max_execution_time_seconds=60,
)
```

### RuntimePolicy

Limits code complexity:

```python
RuntimePolicy(
    max_code_complexity=50,  # AST node count
    max_code_lines=500,
)
```

## Static Analysis

Before sandbox execution, code is parsed into an AST and checked for:

- Forbidden module imports
- `eval()` / `exec()` calls
- `__import__()` calls
- Dangerous builtins (`compile`, `globals`, `locals`, `vars`, `getattr`, `setattr`, `delattr`)
- File I/O (`open()`)
- Syntax errors

## Audit Trail

Every execution is recorded as an `ExecutionTrace`:

```python
records = harness.audit_recorder.get_records(endpoint_name="orders", limit=50)
for trace in records:
    print(f"[{trace.timestamp}] {trace.intent_raw} -> {trace.execution_duration_ms}ms")
```

### Choosing a recorder

Two recorders ship in the box, both satisfying the same `AuditRecorderProtocol`:

| Recorder | Storage | When to use |
|---|---|---|
| `InMemoryAuditRecorder` | Process memory, bounded ring buffer | Dev, tests, single-process demos |
| `SqliteAuditRecorder` | Local SQLite file (stdlib `sqlite3`) | Production, dashboards, post-mortems |

```python
from agenticapi.harness import HarnessEngine
from agenticapi.harness.audit import SqliteAuditRecorder

recorder = SqliteAuditRecorder(path="./audit.sqlite", max_traces=100_000)
harness = HarnessEngine(audit_recorder=recorder, policies=[...])
```

`SqliteAuditRecorder` serializes writes behind an `asyncio.Lock` and dispatches blocking SQLite work through `asyncio.to_thread`, so it's safe to share across concurrent requests without blocking the event loop. Two indices are created on first use — `(timestamp DESC)` and `(endpoint_name)` — keeping the standard dashboard queries fast.

Additional helpers beyond the shared protocol: `iter_since(datetime)` for streaming recent traces to a dashboard, `vacuum_older_than(cutoff)` for retention policies, and `count()` / `clear()` / `close()` for administrative workflows.

See [API Reference → Audit](../api/audit.md) for the full signatures.
