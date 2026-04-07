"""Sandbox runtime base classes.

Defines the abstract base for sandbox execution environments and
the data classes for resource limits, metrics, and results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Resource limits for sandbox execution.

    Attributes:
        max_cpu_seconds: Maximum CPU time allowed in seconds.
        max_memory_mb: Maximum memory usage in megabytes.
        max_execution_time_seconds: Maximum wall-clock time in seconds.
    """

    max_cpu_seconds: float = 30.0
    max_memory_mb: int = 512
    max_execution_time_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class ResourceMetrics:
    """Metrics collected during sandbox execution.

    Attributes:
        cpu_time_ms: CPU time consumed in milliseconds.
        memory_peak_mb: Peak memory usage in megabytes.
        wall_time_ms: Wall-clock time in milliseconds.
    """

    cpu_time_ms: float
    memory_peak_mb: float
    wall_time_ms: float


@dataclass(slots=True)
class SandboxResult:
    """Result of sandbox code execution.

    Attributes:
        output: The primary output of the executed code.
        return_value: The return value of the executed code.
        metrics: Resource usage metrics from execution.
        stdout: Captured standard output.
        stderr: Captured standard error.
    """

    output: Any
    return_value: Any
    metrics: ResourceMetrics
    stdout: str = ""
    stderr: str = ""


class SandboxRuntime(ABC):
    """Abstract base class for sandbox execution environments.

    Provides isolated code execution with resource limits and metrics
    collection. Implementations must support async context manager
    protocol for resource cleanup.

    Phase 1: ProcessSandbox (subprocess-based isolation)
    Phase 2: ContainerSandbox (container-based isolation)
    """

    @abstractmethod
    async def execute(
        self,
        code: str,
        tools: Any,
        resource_limits: ResourceLimits,
    ) -> SandboxResult:
        """Execute code in the sandbox.

        Args:
            code: Python source code to execute.
            tools: ToolRegistry or similar providing available tools.
            resource_limits: Resource constraints for execution.

        Returns:
            SandboxResult with output, return value, and metrics.

        Raises:
            SandboxViolation: If a security violation is detected.
            CodeExecutionError: If the code fails to execute.
        """
        ...

    @abstractmethod
    async def __aenter__(self) -> SandboxRuntime:
        """Enter the sandbox context."""
        ...

    @abstractmethod
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the sandbox context and clean up resources."""
        ...
