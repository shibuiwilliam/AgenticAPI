# Audit

The audit subsystem records every harness execution as an `ExecutionTrace` — intent, generated code, policy results, tool calls, cost, and errors. Recorders are pluggable via the `AuditRecorderProtocol`; ship-in-memory for dev or SQLite for production.

## AuditRecorderProtocol

::: agenticapi.harness.audit.recorder.AuditRecorderProtocol

## InMemoryAuditRecorder

Bounded in-memory storage — fast, but wiped on process restart. Use for development, tests, and single-process demos.

::: agenticapi.harness.audit.recorder.InMemoryAuditRecorder

## SqliteAuditRecorder

Persistent audit storage backed by the Python standard library `sqlite3` module — zero new dependencies, survives process restarts, and exposes query helpers suitable for admin dashboards.

```python
from agenticapi.harness import HarnessEngine
from agenticapi.harness.audit import SqliteAuditRecorder

recorder = SqliteAuditRecorder(path="./audit.sqlite", max_traces=100_000)
harness = HarnessEngine(audit_recorder=recorder, policies=[...])
```

Writes are serialized through an `asyncio.Lock` and dispatched via `asyncio.to_thread`, so the recorder is safe to share across concurrent requests without starving the event loop. Two indices are created on first use: `(timestamp DESC)` for recency queries and `(endpoint_name)` for per-endpoint dashboards.

::: agenticapi.harness.audit.sqlite_store.SqliteAuditRecorder

## ExecutionTrace

::: agenticapi.harness.audit.trace.ExecutionTrace

## Exporters

::: agenticapi.harness.audit.exporters.ConsoleExporter

::: agenticapi.harness.audit.exporters.CompositeExporter
