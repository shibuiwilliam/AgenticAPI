"""Tests for sandbox execution monitors."""

from __future__ import annotations

from agenticapi.harness.sandbox.base import ResourceLimits, ResourceMetrics, SandboxResult
from agenticapi.harness.sandbox.monitors import OutputSizeMonitor, ResourceMonitor


def _make_result(
    *,
    cpu_time_ms: float = 100,
    memory_peak_mb: float = 50,
    wall_time_ms: float = 200,
    return_value: object = None,
    stdout: str = "",
    stderr: str = "",
) -> SandboxResult:
    return SandboxResult(
        output=return_value,
        return_value=return_value,
        metrics=ResourceMetrics(
            cpu_time_ms=cpu_time_ms,
            memory_peak_mb=memory_peak_mb,
            wall_time_ms=wall_time_ms,
        ),
        stdout=stdout,
        stderr=stderr,
    )


class TestResourceMonitor:
    async def test_passes_within_limits(self) -> None:
        limits = ResourceLimits(max_cpu_seconds=10, max_memory_mb=512, max_execution_time_seconds=60)
        monitor = ResourceMonitor(limits=limits)
        result = await monitor.on_execution_complete(
            _make_result(cpu_time_ms=100, memory_peak_mb=50, wall_time_ms=200),
            code="x = 1",
        )
        assert result.passed is True
        assert len(result.violations) == 0

    async def test_cpu_limit_exceeded(self) -> None:
        limits = ResourceLimits(max_cpu_seconds=1)
        monitor = ResourceMonitor(limits=limits)
        result = await monitor.on_execution_complete(
            _make_result(cpu_time_ms=2000),
            code="x = 1",
        )
        assert result.passed is False
        assert any("CPU" in v for v in result.violations)

    async def test_memory_limit_exceeded(self) -> None:
        limits = ResourceLimits(max_memory_mb=100)
        monitor = ResourceMonitor(limits=limits)
        result = await monitor.on_execution_complete(
            _make_result(memory_peak_mb=200),
            code="x = 1",
        )
        assert result.passed is False
        assert any("Memory" in v for v in result.violations)

    async def test_wall_time_limit_exceeded(self) -> None:
        limits = ResourceLimits(max_execution_time_seconds=1)
        monitor = ResourceMonitor(limits=limits)
        result = await monitor.on_execution_complete(
            _make_result(wall_time_ms=2000),
            code="x = 1",
        )
        assert result.passed is False
        assert any("Wall time" in v for v in result.violations)

    async def test_cpu_approaching_limit_generates_warning(self) -> None:
        limits = ResourceLimits(max_cpu_seconds=1)
        monitor = ResourceMonitor(limits=limits)
        result = await monitor.on_execution_complete(
            _make_result(cpu_time_ms=850),
            code="x = 1",
        )
        assert result.passed is True
        assert any("CPU" in w for w in result.warnings)


class TestOutputSizeMonitor:
    async def test_small_output_passes(self) -> None:
        monitor = OutputSizeMonitor(max_output_bytes=1_000_000)
        result = await monitor.on_execution_complete(
            _make_result(return_value={"count": 42}, stdout="ok"),
            code="x = 1",
        )
        assert result.passed is True

    async def test_large_output_fails(self) -> None:
        monitor = OutputSizeMonitor(max_output_bytes=100)
        large_data = "x" * 200
        result = await monitor.on_execution_complete(
            _make_result(return_value=large_data),
            code="x = 1",
        )
        assert result.passed is False
        assert any("Output size" in v for v in result.violations)

    async def test_none_return_value(self) -> None:
        monitor = OutputSizeMonitor(max_output_bytes=1000)
        result = await monitor.on_execution_complete(
            _make_result(return_value=None),
            code="x = 1",
        )
        assert result.passed is True
