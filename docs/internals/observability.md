# Observability

AgenticAPI has a real observability substrate, but the current implementation is a mix of:

- automatic framework instrumentation
- optional helper APIs for custom code paths
- graceful no-op behavior when telemetry dependencies are absent

This document describes the live behavior in the current tree.

## Core Modules

- `src/agenticapi/observability/tracing.py`
- `src/agenticapi/observability/metrics.py`
- `src/agenticapi/observability/propagation.py`
- `src/agenticapi/observability/semconv.py`

## What Exists Today

### Tracing

`configure_tracing(...)` and `get_tracer()` are implemented.

- When OpenTelemetry is installed and configured, framework code can emit spans.
- When it is not installed, the helpers fall back to no-op behavior instead of breaking the request path.

### Metrics

`configure_metrics(...)` and the `record_*` helpers are implemented.

- Metric instruments are created once.
- Recording helpers are safe to call even when metrics are not configured.
- `AgenticApp(metrics_url="/metrics")` can expose a built-in Prometheus-style scrape route.

### Trace propagation

W3C trace-context helpers are implemented:

- `extract_context_from_headers(...)`
- `inject_context_into_headers(...)`
- `headers_with_traceparent(...)`

These are useful when new features call downstream services directly.

### Semantic conventions

`semconv.py` defines framework-specific attribute and span-name enums so instrumentation code does not hard-code raw strings everywhere.

## Automatic Coverage Today

The following paths are wired automatically in the current implementation:

- request count and duration at the `AgenticApp` boundary
- intent-parsing LLM usage in `IntentParser`
- metrics route registration when `metrics_url` is configured

Some other instrumentation exists in code, but should not be described as universal automatic coverage yet.

## Coverage That Is Still Partial

These areas have helper support, but are not emitted automatically across every execution mode:

- policy denials
- budget blocks
- tool calls
- tool-first execution
- extension-driven execution such as the Claude Agent SDK runner
- complete cost attribution for every LLM interaction in the system

When building new runtime paths, call the `record_*` helpers explicitly rather than assuming the framework will capture everything.

## Metric Helpers

The metrics module exposes typed helper functions such as:

```python
from agenticapi.observability import (
    record_budget_block,
    record_llm_usage,
    record_policy_denial,
    record_request,
    record_sandbox_violation,
    record_tool_call,
)
```

These helpers are the preferred extension mechanism for new code paths because they preserve the canonical metric names and labels.

## Built-In Metrics Route

Prefer the app constructor when you want a scrape endpoint:

```python
from agenticapi import AgenticApp

app = AgenticApp(
    title="orders",
    metrics_url="/metrics",
)
```

That route is registered by the framework. If the telemetry stack is unavailable, the endpoint still exists and returns an empty exposition rather than failing the app.

## Tracing Guidance

Use the tracing helpers for:

- request-bound spans
- outbound HTTP calls
- tool dispatch
- extension bridges

Avoid inventing new attribute names when a value already belongs in:

- `GenAIAttributes`
- `AgenticAPIAttributes`
- `SpanNames`

## No-Op Behavior

No-op behavior is part of the API contract.

- Missing telemetry packages must not break app startup.
- Shared libraries inside the repo should call observability helpers unconditionally.
- Feature code should not grow lots of `if telemetry_enabled:` branches.

## Persistent Audit Is Separate

Audit is related to observability, but it is not the same subsystem.

- Metrics and traces are operational telemetry.
- `AuditRecorder` and `SqliteAuditRecorder` are the durable execution record.

Do not describe SQLite audit storage as if it were just another metric backend.

## Current Development Priorities

If you are extending observability, the highest-value gaps are:

1. Broader automatic metrics around tool-first execution and budget failures
2. Better automatic coverage for extension-driven LLM interactions
3. Clearer trace stitching between streaming, approval pause/resume, and replay paths
4. Consistent cost attribution across all LLM execution modes
