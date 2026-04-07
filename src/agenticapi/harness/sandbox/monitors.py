"""Runtime monitors for sandbox execution.

Monitors observe execution results and check for violations such as
resource limit exceedance or oversized output. They run after
sandbox execution completes.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from agenticapi.harness.sandbox.base import ResourceLimits, SandboxResult

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MonitorResult:
    """Result of a monitor check.

    Attributes:
        passed: Whether the check passed without violations.
        warnings: Non-blocking warnings.
        violations: Blocking violations that should stop execution.
    """

    passed: bool
    warnings: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)


@runtime_checkable
class ExecutionMonitor(Protocol):
    """Protocol for sandbox execution monitors.

    Monitors are invoked after sandbox execution completes and can
    check resource usage, output size, or other execution properties.
    """

    async def on_execution_complete(
        self,
        result: SandboxResult,
        *,
        code: str,
    ) -> MonitorResult:
        """Check the execution result.

        Args:
            result: The sandbox execution result.
            code: The code that was executed.

        Returns:
            MonitorResult indicating pass or fail.
        """
        ...


class ResourceMonitor:
    """Monitors resource usage against configured limits.

    Checks that CPU time, memory, and wall time stayed within
    the configured resource limits.

    Example:
        monitor = ResourceMonitor(limits=ResourceLimits(max_cpu_seconds=10))
        result = await monitor.on_execution_complete(sandbox_result, code="...")
    """

    def __init__(self, *, limits: ResourceLimits) -> None:
        """Initialize with resource limits to check against.

        Args:
            limits: The resource limits to enforce.
        """
        self._limits = limits

    async def on_execution_complete(
        self,
        result: SandboxResult,
        *,
        code: str,
    ) -> MonitorResult:
        """Check resource usage against limits.

        Args:
            result: The sandbox execution result.
            code: The code that was executed.

        Returns:
            MonitorResult with violations if limits exceeded.
        """
        violations: list[str] = []
        warnings: list[str] = []

        metrics = result.metrics

        cpu_limit_ms = self._limits.max_cpu_seconds * 1000
        if metrics.cpu_time_ms > cpu_limit_ms:
            violations.append(f"CPU time {metrics.cpu_time_ms:.1f}ms exceeded limit of {cpu_limit_ms:.1f}ms")
        elif metrics.cpu_time_ms > cpu_limit_ms * 0.8:
            warnings.append(f"CPU time {metrics.cpu_time_ms:.1f}ms approaching limit of {cpu_limit_ms:.1f}ms")

        if metrics.memory_peak_mb > self._limits.max_memory_mb:
            violations.append(f"Memory {metrics.memory_peak_mb:.1f}MB exceeded limit of {self._limits.max_memory_mb}MB")

        wall_limit_ms = self._limits.max_execution_time_seconds * 1000
        if metrics.wall_time_ms > wall_limit_ms:
            violations.append(f"Wall time {metrics.wall_time_ms:.1f}ms exceeded limit of {wall_limit_ms:.1f}ms")

        passed = len(violations) == 0

        if not passed:
            logger.warning(
                "resource_monitor_violation",
                violations=violations,
                cpu_time_ms=metrics.cpu_time_ms,
                memory_peak_mb=metrics.memory_peak_mb,
                wall_time_ms=metrics.wall_time_ms,
            )

        return MonitorResult(passed=passed, warnings=warnings, violations=violations)


class OutputSizeMonitor:
    """Monitors output size to prevent memory issues.

    Checks that the combined size of stdout, stderr, and return value
    does not exceed a configurable limit.

    Example:
        monitor = OutputSizeMonitor(max_output_bytes=1_000_000)
        result = await monitor.on_execution_complete(sandbox_result, code="...")
    """

    def __init__(self, *, max_output_bytes: int = 1_000_000) -> None:
        """Initialize with maximum output size.

        Args:
            max_output_bytes: Maximum allowed output size in bytes.
        """
        self._max_output_bytes = max_output_bytes

    async def on_execution_complete(
        self,
        result: SandboxResult,
        *,
        code: str,
    ) -> MonitorResult:
        """Check output size against limit.

        Args:
            result: The sandbox execution result.
            code: The code that was executed.

        Returns:
            MonitorResult with violations if output too large.
        """
        total_size = sys.getsizeof(result.stdout) + sys.getsizeof(result.stderr)

        try:
            total_size += len(json.dumps(result.return_value, default=str).encode())
        except (TypeError, ValueError):
            total_size += sys.getsizeof(result.return_value)

        violations: list[str] = []
        warnings: list[str] = []

        if total_size > self._max_output_bytes:
            violations.append(f"Output size {total_size} bytes exceeded limit of {self._max_output_bytes} bytes")
        elif total_size > self._max_output_bytes * 0.8:
            warnings.append(f"Output size {total_size} bytes approaching limit of {self._max_output_bytes} bytes")

        passed = len(violations) == 0

        if not passed:
            logger.warning("output_size_monitor_violation", total_size=total_size)

        return MonitorResult(passed=passed, warnings=warnings, violations=violations)
