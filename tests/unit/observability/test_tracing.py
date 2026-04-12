"""Unit tests for ``agenticapi.observability.tracing``.

These tests run with ``opentelemetry`` *not* installed (the framework
goes through its no-op fallback). The point of A1 is that nothing
breaks in that mode — every call site stays callable, every span
operation is a cheap no-op.
"""

from __future__ import annotations

import pytest

from agenticapi.observability import (
    AgenticAPIAttributes,
    GenAIAttributes,
    SpanNames,
    configure_tracing,
    get_tracer,
    is_otel_available,
    is_tracing_configured,
    reset_for_tests,
    should_record_prompt_bodies,
)


@pytest.fixture(autouse=True)
def _reset_tracing():
    yield
    reset_for_tests()


class TestNoopTracerWithoutOTEL:
    def test_otel_not_available_in_test_env(self) -> None:
        """The test env intentionally has OTEL uninstalled."""
        # If this fails, install/uninstall OTEL via uv pip first.
        assert is_otel_available() is False

    def test_get_tracer_returns_noop(self) -> None:
        tracer = get_tracer()
        assert type(tracer).__name__ == "_NoopTracer"

    def test_noop_span_accepts_attributes(self) -> None:
        tracer = get_tracer()
        with tracer.start_as_current_span(SpanNames.AGENT_REQUEST.value) as span:
            span.set_attribute(AgenticAPIAttributes.ENDPOINT_NAME.value, "orders.query")
            span.set_attribute(GenAIAttributes.REQUEST_MODEL.value, "claude-sonnet-4-6")
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS.value, 1234)
            # No exception is the assertion.

    def test_noop_span_supports_events_and_status(self) -> None:
        tracer = get_tracer()
        with tracer.start_as_current_span(SpanNames.SANDBOX_EXECUTE.value) as span:
            span.add_event("policy_denied", {"policy": "CodePolicy"})
            span.set_status("ERROR", "denied")
            span.record_exception(ValueError("test"))

    def test_configure_tracing_warns_but_does_not_raise(self, caplog) -> None:
        """When OTEL isn't installed, configure_tracing logs and returns."""
        configure_tracing(service_name="test")
        assert is_tracing_configured() is False  # never flips to True

    def test_should_record_prompt_bodies_default_false(self) -> None:
        assert should_record_prompt_bodies() is False


class TestSemanticConventions:
    def test_gen_ai_attributes_match_upstream(self) -> None:
        """Spot-check the most-load-bearing constants against the spec."""
        assert GenAIAttributes.SYSTEM == "gen_ai.system"
        assert GenAIAttributes.REQUEST_MODEL == "gen_ai.request.model"
        assert GenAIAttributes.RESPONSE_MODEL == "gen_ai.response.model"
        assert GenAIAttributes.USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"
        assert GenAIAttributes.USAGE_OUTPUT_TOKENS == "gen_ai.usage.output_tokens"

    def test_agenticapi_attributes_have_namespace(self) -> None:
        """Every AgenticAPI-specific attribute uses the agenticapi.* namespace."""
        for attr in AgenticAPIAttributes:
            assert attr.value.startswith("agenticapi.")

    def test_span_names_use_dotted_notation(self) -> None:
        for name in SpanNames:
            assert "." in name.value
