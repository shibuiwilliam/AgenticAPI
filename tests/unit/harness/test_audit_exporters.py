"""Tests for audit exporters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

from agenticapi.harness.audit.exporters import (
    AuditExporter,
    CompositeExporter,
    ConsoleExporter,
)
from agenticapi.harness.audit.trace import ExecutionTrace

if TYPE_CHECKING:
    import pytest


def _make_trace(
    *,
    trace_id: str = "test_trace",
    endpoint_name: str = "test",
    error: str | None = None,
) -> ExecutionTrace:
    return ExecutionTrace(
        trace_id=trace_id,
        endpoint_name=endpoint_name,
        timestamp=datetime.now(tz=UTC),
        intent_raw="test intent",
        intent_action="read",
        generated_code="result = 42",
        execution_duration_ms=10.0,
        error=error,
    )


class TestConsoleExporter:
    async def test_export_prints_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        exporter = ConsoleExporter(pretty=False)
        trace = _make_trace()
        await exporter.export(trace)
        output = capsys.readouterr().out
        assert "test_trace" in output
        assert "test intent" in output

    async def test_export_pretty_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        exporter = ConsoleExporter(pretty=True)
        trace = _make_trace()
        await exporter.export(trace)
        output = capsys.readouterr().out
        assert "\n" in output  # Pretty-printed has newlines

    async def test_export_includes_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        exporter = ConsoleExporter(pretty=False)
        trace = _make_trace(error="something failed")
        await exporter.export(trace)
        output = capsys.readouterr().out
        assert "something failed" in output


class TestCompositeExporter:
    async def test_fans_out_to_all_exporters(self) -> None:
        mock1 = AsyncMock()
        mock2 = AsyncMock()
        composite = CompositeExporter([mock1, mock2])

        trace = _make_trace()
        await composite.export(trace)

        mock1.export.assert_called_once_with(trace)
        mock2.export.assert_called_once_with(trace)

    async def test_continues_on_exporter_failure(self) -> None:
        failing = AsyncMock()
        failing.export.side_effect = RuntimeError("boom")
        succeeding = AsyncMock()

        composite = CompositeExporter([failing, succeeding])

        trace = _make_trace()
        await composite.export(trace)

        # Second exporter should still be called
        succeeding.export.assert_called_once_with(trace)

    async def test_empty_exporters_does_nothing(self) -> None:
        composite = CompositeExporter([])
        trace = _make_trace()
        await composite.export(trace)  # Should not raise


class TestOpenTelemetryExporter:
    def test_import_error_without_otel(self) -> None:
        # OpenTelemetry is not in the dev dependencies, so this should fail
        # (unless it's installed)
        try:
            from agenticapi.harness.audit.exporters import OpenTelemetryExporter

            OpenTelemetryExporter(service_name="test")
        except ImportError as exc:
            assert "opentelemetry" in str(exc).lower()


class TestAuditExporterProtocol:
    def test_console_exporter_satisfies_protocol(self) -> None:
        assert isinstance(ConsoleExporter(), AuditExporter)
