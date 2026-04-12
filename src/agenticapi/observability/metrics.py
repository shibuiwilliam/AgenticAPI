"""Prometheus / OpenTelemetry metrics for AgenticAPI.

Production agent APIs need metrics to SLO and alert on. This module
exposes the canonical AgenticAPI metric set as a thin wrapper that
degrades cleanly to no-op when ``opentelemetry-api`` (or
``opentelemetry-sdk``) is not installed — same pattern as
:mod:`agenticapi.observability.tracing`.

Metrics surfaced
----------------

* ``agenticapi_requests_total{endpoint, status}`` — counter
* ``agenticapi_request_duration_seconds{endpoint}`` — histogram
* ``agenticapi_policy_denials_total{policy, endpoint}`` — counter
* ``agenticapi_sandbox_violations_total{kind, endpoint}`` — counter
* ``agenticapi_llm_tokens_total{model, kind}`` — counter (input / output)
* ``agenticapi_llm_cost_usd_total{model}`` — counter
* ``agenticapi_llm_latency_seconds{model}`` — histogram
* ``agenticapi_tool_calls_total{tool, endpoint}`` — counter
* ``agenticapi_budget_blocks_total{scope}`` — counter

The framework records these at the right call sites; users get them
for free by setting ``AgenticApp(metrics_url='/metrics')``. When the
optional metrics deps are missing, the recorder is a no-op so the hot
path stays fast.

Why a thin wrapper, not direct OTEL calls.
    Centralising every metric here means we have one place to add new
    counters, document semantics, switch backends, or stub things in
    tests. The API call sites only ever import the module-level
    helpers (``record_request``, ``record_llm_usage`` …) and don't
    care which exporter is wired up underneath.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lazy capability detection
# ---------------------------------------------------------------------------


def _try_import_metrics_api() -> Any:
    try:
        from opentelemetry import metrics as otel_metrics  # type: ignore[import-not-found]
    except ImportError:
        return None
    return otel_metrics


_OTEL_METRICS = _try_import_metrics_api()
_METER: Any = None
_INSTRUMENTS: dict[str, Any] = {}
_PROMETHEUS_READER: Any = None


def is_metrics_available() -> bool:
    """True when ``opentelemetry-api`` is importable."""
    return _OTEL_METRICS is not None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def configure_metrics(
    *,
    service_name: str = "agenticapi",
    enable_prometheus: bool = True,
) -> None:
    """Initialise the OpenTelemetry meter provider.

    Safe to call multiple times — subsequent calls are no-ops. Safe
    to call when ``opentelemetry-sdk`` is not installed: logs a
    warning and leaves the recorder in no-op mode.

    Args:
        service_name: ``service.name`` resource attribute.
        enable_prometheus: When True (default) and the optional
            ``opentelemetry-exporter-prometheus`` package is installed,
            wires up an in-process Prometheus reader so the
            ``/metrics`` HTTP endpoint can scrape it.
    """
    global _METER, _PROMETHEUS_READER

    if _METER is not None:
        return

    if _OTEL_METRICS is None:
        logger.warning(
            "otel_metrics_not_installed",
            message=(
                "configure_metrics() called but opentelemetry-api is not installed. "
                "Install with: pip install opentelemetry-api opentelemetry-sdk"
            ),
        )
        return

    try:
        from opentelemetry.sdk.metrics import MeterProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "otel_metrics_sdk_not_installed",
            message=(
                "configure_metrics() called but opentelemetry-sdk is not installed. "
                "Install with: pip install opentelemetry-sdk"
            ),
        )
        return

    readers: list[Any] = []
    if enable_prometheus:
        try:
            from opentelemetry.exporter.prometheus import (  # type: ignore[import-not-found]
                PrometheusMetricReader,
            )

            _PROMETHEUS_READER = PrometheusMetricReader()
            readers.append(_PROMETHEUS_READER)
        except ImportError:
            logger.info(
                "prometheus_exporter_not_installed",
                message=(
                    "Prometheus metrics requested but opentelemetry-exporter-prometheus "
                    "is not installed. Skipping. Install with: "
                    "pip install opentelemetry-exporter-prometheus"
                ),
            )

    resource = Resource.create({"service.name": service_name})
    provider = MeterProvider(resource=resource, metric_readers=readers)
    _OTEL_METRICS.set_meter_provider(provider)
    _METER = _OTEL_METRICS.get_meter("agenticapi")
    _build_instruments()
    logger.info(
        "metrics_configured",
        service_name=service_name,
        prometheus_enabled=_PROMETHEUS_READER is not None,
    )


def _build_instruments() -> None:
    """Create the canonical AgenticAPI metric instruments."""
    if _METER is None:
        return
    _INSTRUMENTS["requests_total"] = _METER.create_counter(
        name="agenticapi_requests_total",
        description="Number of agent endpoint requests handled.",
        unit="1",
    )
    _INSTRUMENTS["request_duration_seconds"] = _METER.create_histogram(
        name="agenticapi_request_duration_seconds",
        description="Wall-clock duration of agent endpoint requests.",
        unit="s",
    )
    _INSTRUMENTS["policy_denials_total"] = _METER.create_counter(
        name="agenticapi_policy_denials_total",
        description="Policy denials at the harness level.",
        unit="1",
    )
    _INSTRUMENTS["sandbox_violations_total"] = _METER.create_counter(
        name="agenticapi_sandbox_violations_total",
        description="Sandbox violations detected during execution.",
        unit="1",
    )
    _INSTRUMENTS["llm_tokens_total"] = _METER.create_counter(
        name="agenticapi_llm_tokens_total",
        description="LLM tokens consumed.",
        unit="1",
    )
    _INSTRUMENTS["llm_cost_usd_total"] = _METER.create_counter(
        name="agenticapi_llm_cost_usd_total",
        description="LLM cost accumulated.",
        unit="USD",
    )
    _INSTRUMENTS["llm_latency_seconds"] = _METER.create_histogram(
        name="agenticapi_llm_latency_seconds",
        description="LLM call latency.",
        unit="s",
    )
    _INSTRUMENTS["tool_calls_total"] = _METER.create_counter(
        name="agenticapi_tool_calls_total",
        description="Tool invocations from agent endpoints.",
        unit="1",
    )
    _INSTRUMENTS["budget_blocks_total"] = _METER.create_counter(
        name="agenticapi_budget_blocks_total",
        description="Cost budget breaches blocked by BudgetPolicy.",
        unit="1",
    )
    # Phase C5: approved-code cache hit/miss counters. Hits indicate
    # skipped LLM calls; misses indicate fresh code generation.
    _INSTRUMENTS["code_cache_hits_total"] = _METER.create_counter(
        name="agenticapi_code_cache_hits_total",
        description="Approved-code cache hits (skipped code generation).",
        unit="1",
    )
    _INSTRUMENTS["code_cache_misses_total"] = _METER.create_counter(
        name="agenticapi_code_cache_misses_total",
        description="Approved-code cache misses (fresh code generation required).",
        unit="1",
    )
    # Phase B5: prompt-injection detections. Blocks counts the total
    # number of requests PromptInjectionPolicy denied.
    _INSTRUMENTS["prompt_injection_blocks_total"] = _METER.create_counter(
        name="agenticapi_prompt_injection_blocks_total",
        description="Prompt-injection detections blocked at ingress.",
        unit="1",
    )


# ---------------------------------------------------------------------------
# Recording helpers (no-op when not configured)
# ---------------------------------------------------------------------------


def _record_counter(name: str, value: int | float, attributes: dict[str, str]) -> None:
    instrument = _INSTRUMENTS.get(name)
    if instrument is None:
        return
    instrument.add(value, attributes=attributes)


def _record_histogram(name: str, value: float, attributes: dict[str, str]) -> None:
    instrument = _INSTRUMENTS.get(name)
    if instrument is None:
        return
    instrument.record(value, attributes=attributes)


def record_request(*, endpoint: str, status: str, duration_seconds: float) -> None:
    """Record one completed agent request."""
    _record_counter("requests_total", 1, {"endpoint": endpoint, "status": status})
    _record_histogram("request_duration_seconds", duration_seconds, {"endpoint": endpoint})


def record_policy_denial(*, policy: str, endpoint: str) -> None:
    _record_counter("policy_denials_total", 1, {"policy": policy, "endpoint": endpoint})


def record_sandbox_violation(*, kind: str, endpoint: str) -> None:
    _record_counter("sandbox_violations_total", 1, {"kind": kind, "endpoint": endpoint})


def record_llm_usage(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None = None,
    latency_seconds: float | None = None,
) -> None:
    _record_counter("llm_tokens_total", input_tokens, {"model": model, "kind": "input"})
    _record_counter("llm_tokens_total", output_tokens, {"model": model, "kind": "output"})
    if cost_usd is not None:
        _record_counter("llm_cost_usd_total", cost_usd, {"model": model})
    if latency_seconds is not None:
        _record_histogram("llm_latency_seconds", latency_seconds, {"model": model})


def record_tool_call(*, tool: str, endpoint: str) -> None:
    _record_counter("tool_calls_total", 1, {"tool": tool, "endpoint": endpoint})


def record_budget_block(*, scope: str) -> None:
    _record_counter("budget_blocks_total", 1, {"scope": scope})


def record_code_cache_hit(*, endpoint: str) -> None:
    """Count an approved-code cache hit (Phase C5)."""
    _record_counter("code_cache_hits_total", 1, {"endpoint": endpoint})


def record_code_cache_miss(*, endpoint: str) -> None:
    """Count an approved-code cache miss (Phase C5)."""
    _record_counter("code_cache_misses_total", 1, {"endpoint": endpoint})


def record_prompt_injection_block(*, endpoint: str, pattern: str) -> None:
    """Count a PromptInjectionPolicy block (Phase B5)."""
    _record_counter(
        "prompt_injection_blocks_total",
        1,
        {"endpoint": endpoint, "pattern": pattern},
    )


# ---------------------------------------------------------------------------
# Prometheus scrape endpoint
# ---------------------------------------------------------------------------


def render_prometheus_exposition() -> tuple[bytes, str]:
    """Return the current Prometheus exposition (body, content_type).

    Returns ``(b"", "text/plain")`` when metrics are not configured.
    """
    if _PROMETHEUS_READER is None:
        return (b"", "text/plain; version=0.0.4")
    try:
        from prometheus_client import generate_latest  # type: ignore[import-not-found]
        from prometheus_client.exposition import CONTENT_TYPE_LATEST  # type: ignore[import-not-found]
    except ImportError:
        return (b"", "text/plain; version=0.0.4")

    body = generate_latest()  # The OTEL Prometheus reader registers with the default registry.
    return (body, CONTENT_TYPE_LATEST)


def reset_for_tests() -> None:
    """Reset module-global state. Test-only helper."""
    global _METER, _PROMETHEUS_READER
    _METER = None
    _PROMETHEUS_READER = None
    _INSTRUMENTS.clear()


__all__ = [
    "configure_metrics",
    "is_metrics_available",
    "record_budget_block",
    "record_code_cache_hit",
    "record_code_cache_miss",
    "record_llm_usage",
    "record_policy_denial",
    "record_prompt_injection_block",
    "record_request",
    "record_sandbox_violation",
    "record_tool_call",
    "render_prometheus_exposition",
    "reset_for_tests",
]
