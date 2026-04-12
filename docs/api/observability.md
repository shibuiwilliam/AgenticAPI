# Observability

The `agenticapi.observability` subpackage provides OpenTelemetry tracing and Prometheus metrics. All entry points gracefully no-op when the optional dependencies aren't installed.

See the [Observability guide](../guides/observability.md) for setup patterns.

## Tracing

::: agenticapi.observability.tracing.configure_tracing

::: agenticapi.observability.tracing.get_tracer

::: agenticapi.observability.tracing.is_otel_available

::: agenticapi.observability.tracing.is_tracing_configured

::: agenticapi.observability.tracing.should_record_prompt_bodies

::: agenticapi.observability.tracing.reset_for_tests

## Metrics

::: agenticapi.observability.metrics.configure_metrics

::: agenticapi.observability.metrics.is_metrics_available

::: agenticapi.observability.metrics.record_request

::: agenticapi.observability.metrics.record_policy_denial

::: agenticapi.observability.metrics.record_sandbox_violation

::: agenticapi.observability.metrics.record_llm_usage

::: agenticapi.observability.metrics.record_tool_call

::: agenticapi.observability.metrics.record_budget_block

::: agenticapi.observability.metrics.render_prometheus_exposition

## Distributed Trace Context Propagation

W3C `traceparent` and `tracestate` header propagation so AgenticAPI services join traces started by other systems and pass their own trace IDs onward to downstream calls. All functions gracefully no-op when OpenTelemetry propagators aren't installed.

See the [Observability guide → Distributed Propagation](../guides/observability.md#distributed-trace-context-propagation) for usage patterns.

::: agenticapi.observability.propagation.is_propagation_available

::: agenticapi.observability.propagation.extract_context_from_headers

::: agenticapi.observability.propagation.inject_context_into_headers

::: agenticapi.observability.propagation.headers_with_traceparent

## Semantic Conventions

String enums for OpenTelemetry span attributes. `GenAIAttributes` follows the [OpenTelemetry GenAI SIG](https://opentelemetry.io/docs/specs/semconv/gen-ai/) conventions; `AgenticAPIAttributes` adds framework-specific fields.

::: agenticapi.observability.semconv.GenAIAttributes

::: agenticapi.observability.semconv.AgenticAPIAttributes

::: agenticapi.observability.semconv.SpanNames
