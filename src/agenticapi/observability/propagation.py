"""W3C Trace Context propagation helpers.

When AgenticAPI sits in a distributed system — handling requests from
an upstream service or calling out to downstream services via tools —
its traces should join the existing distributed trace, not create
isolated islands. The W3C Trace Context spec
(`traceparent` / `tracestate` headers) is the standard way to do this,
and every modern APM understands it.

This module exposes two helpers:

* :func:`extract_context_from_headers` — read the incoming HTTP
  headers, find any ``traceparent`` value, and return an OpenTelemetry
  context that the next ``start_as_current_span`` call will use as the
  parent. Falls back to the current context when no header is present
  or when OpenTelemetry is not installed.
* :func:`inject_context_into_headers` — for outgoing HTTP calls
  (``HttpClientTool``, A2A, the Claude Agent SDK runner), write the
  current span's ``traceparent`` (and ``tracestate`` if present) into
  an outgoing headers dict.

Both helpers degrade cleanly to **no-ops** when ``opentelemetry-api``
is not installed — they leave the inputs unchanged. That keeps the
framework's "OTel is optional" promise intact.

Phase A5 in :doc:`/CLAUDE_ENHANCE`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lazy capability detection
# ---------------------------------------------------------------------------


def _try_import_propagators() -> Any:
    """Import the OpenTelemetry W3C propagator, or None when not installed."""
    try:
        from opentelemetry import propagate  # type: ignore[import-not-found]
    except ImportError:
        return None
    return propagate


_PROPAGATE = _try_import_propagators()


def is_propagation_available() -> bool:
    """True when the OpenTelemetry propagation API is importable."""
    return _PROPAGATE is not None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_context_from_headers(headers: Mapping[str, str] | None) -> Any:
    """Build an OpenTelemetry context from incoming HTTP headers.

    Args:
        headers: A header mapping (case-insensitive lookups). May be
            ``None`` for callers without an upstream request.

    Returns:
        An OpenTelemetry ``Context`` object that the next
        ``start_as_current_span`` call should use as parent. When
        ``opentelemetry-api`` is not installed, returns ``None``;
        callers can pass ``context=None`` safely to no-op tracers.
    """
    if _PROPAGATE is None or not headers:
        return None
    try:
        return _PROPAGATE.extract(dict(headers))
    except Exception as exc:
        logger.warning("traceparent_extract_failed", error=str(exc))
        return None


def inject_context_into_headers(headers: dict[str, str]) -> dict[str, str]:
    """Mutate ``headers`` in place with the current trace context.

    Safe to call when no span is active and when OpenTelemetry is not
    installed — both cases leave the headers unchanged.

    Args:
        headers: The outgoing HTTP headers dict to update.

    Returns:
        The same ``headers`` dict (returned for fluent chaining).
    """
    if _PROPAGATE is None:
        return headers
    try:
        _PROPAGATE.inject(headers)
    except Exception as exc:
        logger.warning("traceparent_inject_failed", error=str(exc))
    return headers


def headers_with_traceparent(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a fresh dict with the current traceparent injected.

    Convenience wrapper for callers that don't already have a headers
    dict to mutate. Equivalent to::

        out = dict(base or {})
        inject_context_into_headers(out)
        return out
    """
    out: dict[str, str] = dict(base or {})
    inject_context_into_headers(out)
    return out


__all__ = [
    "extract_context_from_headers",
    "headers_with_traceparent",
    "inject_context_into_headers",
    "is_propagation_available",
]
