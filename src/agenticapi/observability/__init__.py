"""Observability primitives for AgenticAPI.

This subpackage provides the framework's OpenTelemetry-native
instrumentation surface. It is **opt-in** and **degrades cleanly to
no-op** when ``opentelemetry-api`` is not installed, so existing
deployments that don't yet care about distributed tracing pay zero
runtime cost.

Typical usage:

    from agenticapi.observability import configure_tracing

    configure_tracing(
        service_name="my-service",
        otlp_endpoint="http://localhost:4318",
    )

Then every request through ``AgenticApp`` automatically produces a
hierarchical span tree with the OpenTelemetry GenAI semantic
conventions (``gen_ai.*``) plus AgenticAPI-specific attributes
(policy verdicts, sandbox events, autonomy levels, etc.).
"""

from __future__ import annotations

from agenticapi.observability.metrics import (
    configure_metrics,
    is_metrics_available,
    record_budget_block,
    record_llm_usage,
    record_policy_denial,
    record_request,
    record_sandbox_violation,
    record_tool_call,
    render_prometheus_exposition,
)
from agenticapi.observability.propagation import (
    extract_context_from_headers,
    headers_with_traceparent,
    inject_context_into_headers,
    is_propagation_available,
)
from agenticapi.observability.semconv import (
    AgenticAPIAttributes,
    GenAIAttributes,
    SpanNames,
)
from agenticapi.observability.tracing import (
    configure_tracing,
    get_tracer,
    is_otel_available,
    is_tracing_configured,
    reset_for_tests,
    should_record_prompt_bodies,
)

__all__ = [
    "AgenticAPIAttributes",
    "GenAIAttributes",
    "SpanNames",
    "configure_metrics",
    "configure_tracing",
    "extract_context_from_headers",
    "get_tracer",
    "headers_with_traceparent",
    "inject_context_into_headers",
    "is_metrics_available",
    "is_otel_available",
    "is_propagation_available",
    "is_tracing_configured",
    "record_budget_block",
    "record_llm_usage",
    "record_policy_denial",
    "record_request",
    "record_sandbox_violation",
    "record_tool_call",
    "render_prometheus_exposition",
    "reset_for_tests",
    "should_record_prompt_bodies",
]
