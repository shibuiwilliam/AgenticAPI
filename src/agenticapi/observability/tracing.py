"""OpenTelemetry tracer bootstrap and lazy import shim.

The OpenTelemetry SDK is an **optional** dependency. The framework
imports cleanly without it, and every instrumentation call site goes
through this module so:

* When ``opentelemetry-api`` is not installed, every span call is a
  cheap no-op (``NoopTracer``) and zero overhead is added to the hot
  path.
* When ``opentelemetry-api`` is installed but :func:`configure_tracing`
  has not been called yet, spans are emitted under the global default
  ``TracerProvider`` (which itself is a no-op until the user wires up
  an exporter).
* When :func:`configure_tracing` has been called, spans flow through
  the user's configured ``TracerProvider``. Common cases — sending to
  an OTLP collector — are handled by ``configure_tracing(otlp_endpoint=...)``
  in one line.

Why this indirection.

Phase 1 already shipped a single ``OpenTelemetryExporter`` that emits
one post-hoc span per execution. Phase A1 is the next step: real,
hierarchical spans wrapping every stage of the pipeline. Doing this
without breaking the no-OTEL-installed case requires the lazy shim
below — every call site looks like:

    from agenticapi.observability import get_tracer, AgenticAPIAttributes

    tracer = get_tracer()
    with tracer.start_as_current_span("agent.intent_parse") as span:
        span.set_attribute(AgenticAPIAttributes.INTENT_RAW, raw[:200])
        intent = await parser.parse(raw)
        return intent

…and works whether or not OTEL is installed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lazy import + capability detection
# ---------------------------------------------------------------------------


def _try_import_otel() -> Any:
    """Return the ``opentelemetry.trace`` module, or ``None`` if missing."""
    try:
        from opentelemetry import trace as otel_trace  # type: ignore[import-not-found]
    except ImportError:
        return None
    return otel_trace


_OTEL_TRACE: Any = _try_import_otel()
_CONFIGURED: bool = False


def is_otel_available() -> bool:
    """True when ``opentelemetry-api`` is importable."""
    return _OTEL_TRACE is not None


def is_tracing_configured() -> bool:
    """True when :func:`configure_tracing` has been called successfully."""
    return _CONFIGURED


# ---------------------------------------------------------------------------
# No-op span / tracer
# ---------------------------------------------------------------------------


class _NoopSpan:
    """A span object that records nothing.

    Implements the subset of the OpenTelemetry ``Span`` API that
    AgenticAPI's instrumentation actually calls. Anything else is a
    silent no-op via ``__getattr__``.
    """

    def set_attribute(self, key: str, value: Any) -> None:
        del key, value

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        del attributes

    def add_event(self, name: str, attributes: Mapping[str, Any] | None = None) -> None:
        del name, attributes

    def set_status(self, status: Any, description: str | None = None) -> None:
        del status, description

    def record_exception(self, exception: BaseException, attributes: Mapping[str, Any] | None = None) -> None:
        del exception, attributes

    def __getattr__(self, name: str) -> Any:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


class _NoopTracer:
    """Tracer that returns no-op spans for every call.

    Used when ``opentelemetry-api`` is not installed. Every method
    matches the corresponding OTEL API surface so call sites can use
    the same code regardless of whether OTEL is configured.

    The signature accepts ``**kwargs`` so callers can pass through
    forward-compatible OTel parameters (``context=``, ``kind=``,
    ``links=``, ``record_exception=``, etc.) without the no-op
    raising.
    """

    @contextmanager
    def start_as_current_span(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[_NoopSpan]:
        del name, attributes, kwargs
        yield _NoopSpan()

    def start_span(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> _NoopSpan:
        del name, attributes, kwargs
        return _NoopSpan()


_NOOP_TRACER = _NoopTracer()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_tracer() -> Any:
    """Return the active tracer.

    When ``opentelemetry-api`` is installed, returns the global
    AgenticAPI tracer (``opentelemetry.trace.get_tracer("agenticapi")``).
    Otherwise returns a no-op tracer that satisfies the same API.
    """
    if _OTEL_TRACE is None:
        return _NOOP_TRACER
    return _OTEL_TRACE.get_tracer("agenticapi")


def configure_tracing(
    *,
    service_name: str = "agenticapi",
    otlp_endpoint: str | None = None,
    resource_attributes: Mapping[str, str] | None = None,
    record_prompt_bodies: bool = False,
) -> None:
    """Initialise the OpenTelemetry tracer provider for AgenticAPI.

    Safe to call multiple times — subsequent calls are no-ops. Safe to
    call when ``opentelemetry-sdk`` is not installed: logs a warning
    and leaves instrumentation in no-op mode.

    Args:
        service_name: The ``service.name`` resource attribute. Shown
            in APM dashboards as the service identifier.
        otlp_endpoint: When set, configures an OTLP HTTP exporter
            pointing at this endpoint. Typical: ``"http://localhost:4318"``
            (the default OpenTelemetry Collector address).
        resource_attributes: Extra resource attributes to attach to
            every span (e.g. ``{"deployment.environment": "prod"}``).
        record_prompt_bodies: When True, the framework includes the
            full prompt text in spans (truncated to 500 chars). When
            False (default), only metadata flows so PII stays out of
            traces. Toggle on cautiously and only when audit
            requirements demand it.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    if _OTEL_TRACE is None:
        logger.warning(
            "otel_not_installed",
            message=(
                "configure_tracing() called but opentelemetry-api is not installed. "
                "Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp"
            ),
        )
        return

    try:
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            BatchSpanProcessor,
        )
    except ImportError:
        logger.warning(
            "otel_sdk_not_installed",
            message=(
                "configure_tracing() called but opentelemetry-sdk is not installed. "
                "Install with: pip install opentelemetry-sdk"
            ),
        )
        return

    attrs: dict[str, str] = {"service.name": service_name}
    if resource_attributes:
        attrs.update(resource_attributes)
    resource = Resource.create(attrs)
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except ImportError:
            logger.warning(
                "otel_otlp_exporter_not_installed",
                message=(
                    "otlp_endpoint set but opentelemetry-exporter-otlp is not installed. "
                    "Install with: pip install opentelemetry-exporter-otlp"
                ),
            )

    _OTEL_TRACE.set_tracer_provider(provider)
    _CONFIGURED = True
    _record_prompt_bodies_state["enabled"] = record_prompt_bodies
    logger.info(
        "tracing_configured",
        service_name=service_name,
        otlp_endpoint=otlp_endpoint,
        record_prompt_bodies=record_prompt_bodies,
    )


# ---------------------------------------------------------------------------
# Privacy toggle for prompt bodies
# ---------------------------------------------------------------------------


_record_prompt_bodies_state: dict[str, bool] = {"enabled": False}


def should_record_prompt_bodies() -> bool:
    """Whether prompt text should be attached to spans (default False)."""
    return _record_prompt_bodies_state["enabled"]


def reset_for_tests() -> None:
    """Reset module-global state. Test-only helper."""
    global _CONFIGURED
    _CONFIGURED = False
    _record_prompt_bodies_state["enabled"] = False


__all__ = [
    "configure_tracing",
    "get_tracer",
    "is_otel_available",
    "is_tracing_configured",
    "reset_for_tests",
    "should_record_prompt_bodies",
]
