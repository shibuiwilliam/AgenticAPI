"""Audit trace exporters.

Provides exporters for sending execution traces to external systems.
Includes a ConsoleExporter for development and an OpenTelemetryExporter
for production observability (requires optional opentelemetry dependency).
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from agenticapi.harness.audit.trace import ExecutionTrace

logger = structlog.get_logger(__name__)


@runtime_checkable
class AuditExporter(Protocol):
    """Protocol for audit trace exporters.

    Implementations send execution traces to external systems
    such as OpenTelemetry, Elasticsearch, or custom backends.
    """

    async def export(self, trace: ExecutionTrace) -> None:
        """Export an execution trace.

        Args:
            trace: The execution trace to export.
        """
        ...


class ConsoleExporter:
    """Exports execution traces to stdout as JSON.

    Useful for development and debugging. Requires no external
    dependencies.

    Example:
        exporter = ConsoleExporter()
        await exporter.export(trace)
    """

    def __init__(self, *, pretty: bool = True) -> None:
        """Initialize the console exporter.

        Args:
            pretty: If True, format JSON with indentation.
        """
        self._pretty = pretty

    async def export(self, trace: ExecutionTrace) -> None:
        """Print the trace as JSON to stdout.

        Args:
            trace: The execution trace to export.
        """
        data = {
            "trace_id": trace.trace_id,
            "endpoint_name": trace.endpoint_name,
            "timestamp": trace.timestamp.isoformat() if trace.timestamp else None,
            "intent_raw": trace.intent_raw,
            "intent_action": trace.intent_action,
            "generated_code": trace.generated_code,
            "reasoning": trace.reasoning,
            "policy_evaluations": trace.policy_evaluations,
            "execution_result": str(trace.execution_result) if trace.execution_result is not None else None,
            "execution_duration_ms": trace.execution_duration_ms,
            "error": trace.error,
            "approval_request_id": trace.approval_request_id,
        }

        indent = 2 if self._pretty else None
        output = json.dumps(data, indent=indent, default=str)
        print(output)

        logger.debug("console_export_complete", trace_id=trace.trace_id)


class OpenTelemetryExporter:
    """Exports execution traces as OpenTelemetry spans.

    Requires the ``opentelemetry-api`` and ``opentelemetry-sdk`` packages.
    These are optional dependencies — an informative ImportError is raised
    if they are not installed.

    Example:
        exporter = OpenTelemetryExporter(service_name="myapp")
        await exporter.export(trace)
    """

    def __init__(
        self,
        *,
        service_name: str = "agenticapi",
        endpoint: str | None = None,
    ) -> None:
        """Initialize the OpenTelemetry exporter.

        Args:
            service_name: The service name for OTEL spans.
            endpoint: Optional OTEL collector endpoint URL.

        Raises:
            ImportError: If opentelemetry packages are not installed.
        """
        try:
            from opentelemetry import trace as otel_trace  # type: ignore[import-not-found]
            from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "OpenTelemetry packages are required for OpenTelemetryExporter. "
                "Install them with: pip install opentelemetry-api opentelemetry-sdk"
            ) from exc

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        otel_trace.set_tracer_provider(provider)
        self._tracer = otel_trace.get_tracer("agenticapi")
        self._service_name = service_name

        logger.info("otel_exporter_initialized", service_name=service_name, endpoint=endpoint)

    async def export(self, trace: ExecutionTrace) -> None:
        """Export an execution trace as an OTEL span.

        Args:
            trace: The execution trace to export.
        """
        with self._tracer.start_as_current_span("agent_execution") as span:
            span.set_attribute("agenticapi.trace_id", trace.trace_id)
            span.set_attribute("agenticapi.endpoint_name", trace.endpoint_name)
            span.set_attribute("agenticapi.intent_action", trace.intent_action)
            span.set_attribute("agenticapi.duration_ms", trace.execution_duration_ms)

            if trace.intent_raw:
                span.set_attribute("agenticapi.intent_raw", trace.intent_raw[:500])

            if trace.generated_code:
                span.set_attribute("agenticapi.generated_code_lines", trace.generated_code.count("\n") + 1)

            if trace.error:
                span.set_attribute("agenticapi.error", trace.error[:500])
                from opentelemetry.trace import StatusCode  # type: ignore[import-not-found]

                span.set_status(StatusCode.ERROR, trace.error[:200])

            if trace.approval_request_id:
                span.set_attribute("agenticapi.approval_request_id", trace.approval_request_id)

        logger.debug("otel_export_complete", trace_id=trace.trace_id)


class CompositeExporter:
    """Fans out trace exports to multiple exporters.

    Example:
        exporter = CompositeExporter([ConsoleExporter(), OpenTelemetryExporter()])
        await exporter.export(trace)
    """

    def __init__(self, exporters: list[AuditExporter]) -> None:
        """Initialize with a list of exporters.

        Args:
            exporters: List of exporters to fan out to.
        """
        self._exporters = exporters

    async def export(self, trace: ExecutionTrace) -> None:
        """Export the trace to all registered exporters in parallel.

        Uses asyncio.gather for concurrent exports. Individual exporter
        failures are logged but do not prevent other exporters from running.

        Args:
            trace: The execution trace to export.
        """
        if not self._exporters:
            return

        results = await asyncio.gather(
            *(exporter.export(trace) for exporter in self._exporters),
            return_exceptions=True,
        )
        for exporter, result in zip(self._exporters, results, strict=True):
            if isinstance(result, Exception):
                logger.error(
                    "exporter_failed",
                    exporter=type(exporter).__name__,
                    trace_id=trace.trace_id,
                    error=str(result),
                )
