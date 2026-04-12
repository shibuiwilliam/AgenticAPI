# Observability

AgenticAPI ships tracing, metrics, and trace-propagation helpers that degrade cleanly to no-ops when telemetry packages are not installed.

## Installation

```bash
# Tracing and metrics
pip install opentelemetry-api opentelemetry-sdk

# Optional Prometheus exporter for /metrics scraping
pip install opentelemetry-exporter-prometheus

# Optional OTLP exporter
pip install opentelemetry-exporter-otlp
```

## Configure Tracing And Metrics

```python
from agenticapi.observability import configure_metrics, configure_tracing

configure_tracing(
    service_name="orders",
    otlp_endpoint="http://tempo:4317",
)
configure_metrics(service_name="orders")
```

These calls are safe when the SDK is missing. The framework falls back to no-op behavior instead of failing startup.

## Exposing `/metrics`

Prefer the built-in app constructor hook:

```python
from agenticapi import AgenticApp

app = AgenticApp(
    title="orders",
    metrics_url="/metrics",
)
```

That route serves the canonical AgenticAPI metrics when metrics are configured. If the telemetry stack is unavailable, it returns an empty exposition rather than breaking the app.

## What Is Automatic Today

Automatic instrumentation currently covers:

- request count and request duration at the app boundary
- intent-parsing LLM usage in `IntentParser`
- built-in metrics route registration when `metrics_url` is configured

## What Is Still Partial

The helper APIs exist for the following areas, but coverage is not automatic across every execution mode yet:

- policy denials
- budget blocks
- tool calls
- tool-first execution
- extension-driven execution
- full cost attribution for every LLM interaction

When you build custom flows, call the helpers explicitly.

## Metric Helpers

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

These helpers preserve the canonical metric names and labels.

## Canonical Metrics

| Metric | Type | Labels |
|---|---|---|
| `agenticapi_requests_total` | counter | `endpoint`, `status` |
| `agenticapi_request_duration_seconds` | histogram | `endpoint` |
| `agenticapi_policy_denials_total` | counter | `policy`, `endpoint` |
| `agenticapi_sandbox_violations_total` | counter | `kind`, `endpoint` |
| `agenticapi_llm_tokens_total` | counter | `model`, `kind` |
| `agenticapi_llm_cost_usd_total` | counter | `model` |
| `agenticapi_llm_latency_seconds` | histogram | `model` |
| `agenticapi_tool_calls_total` | counter | `tool`, `endpoint` |
| `agenticapi_budget_blocks_total` | counter | `scope` |

## Tracing

Use the tracing helpers when you add new framework paths:

```python
from agenticapi.observability import get_tracer, SpanNames

tracer = get_tracer()
with tracer.start_as_current_span(SpanNames.TOOL_CALL):
    ...
```

Attribute enums live in:

- `GenAIAttributes`
- `AgenticAPIAttributes`
- `SpanNames`

## Distributed Trace Context Propagation

The propagation helpers implement W3C trace context:

```python
from agenticapi.observability import (
    extract_context_from_headers,
    headers_with_traceparent,
    inject_context_into_headers,
)
```

Use them when the framework or an extension makes outbound requests to downstream services.

## Cost Attribution

Automatic cost attribution exists in parts of the stack, but not yet everywhere.

- `IntentParser` records LLM usage automatically.
- Other execution modes may need explicit `record_llm_usage(...)` calls.
- If you need complete per-endpoint cost dashboards today, instrument your custom paths rather than assuming universal automatic coverage.

## Persistent Audit Is Separate

Tracing and metrics are not the same as durable audit storage. For durable execution history, pair observability with `SqliteAuditRecorder`.

## Runnable Example

See [`examples/16_observability/app.py`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/16_observability). It demonstrates:

- `configure_tracing(...)`
- `configure_metrics(...)`
- `/metrics`
- `SqliteAuditRecorder`
- explicit metric recording for policy denials and budget blocks
