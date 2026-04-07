"""Testing mock utilities for AgenticAPI.

Provides mock implementations of LLM backends and sandbox runtimes
for unit and integration testing. These allow deterministic testing
without external service dependencies.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from agenticapi.exceptions import SandboxViolation
from agenticapi.harness.sandbox.base import (
    ResourceLimits,
    ResourceMetrics,
    SandboxResult,
    SandboxRuntime,
)
from agenticapi.runtime.llm.mock import MockBackend

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def mock_llm(responses: list[str]) -> Generator[MockBackend]:
    """Context manager that provides a MockBackend with predefined responses.

    Yields a MockBackend configured with the given responses. Responses
    are consumed in FIFO order as generate() is called.

    Args:
        responses: List of response strings to return in order.

    Yields:
        A configured MockBackend instance.

    Example:
        with mock_llm(responses=["SELECT COUNT(*) FROM orders"]) as backend:
            response = await backend.generate(prompt)
            assert response.content == "SELECT COUNT(*) FROM orders"
    """
    backend = MockBackend(responses=responses)
    yield backend


class MockSandbox(SandboxRuntime):
    """Mock sandbox for unit testing.

    Returns predefined results based on pattern matching against the
    executed code. Raises SandboxViolation if the code contains any
    of the denied operations.

    Args:
        allowed_results: Mapping of code substrings to return values.
            If a key is found in the code, its value is used as the
            sandbox output.
        denied_operations: List of code substrings that trigger a
            SandboxViolation when found in the code.

    Example:
        sandbox = MockSandbox(
            allowed_results={"SELECT COUNT(*)": [{"count": 42}]},
            denied_operations=["DROP TABLE"],
        )
        async with sandbox as sb:
            result = await sb.execute("SELECT COUNT(*) FROM orders")
            assert result.return_value == [{"count": 42}]
    """

    def __init__(
        self,
        *,
        allowed_results: dict[str, Any] | None = None,
        denied_operations: list[str] | None = None,
    ) -> None:
        """Initialize the mock sandbox.

        Args:
            allowed_results: Mapping of code substrings to return values.
            denied_operations: List of code substrings that trigger violations.
        """
        self._allowed_results: dict[str, Any] = allowed_results or {}
        self._denied_operations: list[str] = denied_operations or []
        self._execution_count: int = 0

    @property
    def execution_count(self) -> int:
        """Number of execute calls made."""
        return self._execution_count

    async def execute(
        self,
        code: str,
        tools: Any = None,
        resource_limits: ResourceLimits | None = None,
    ) -> SandboxResult:
        """Execute code against mock rules.

        Checks denied operations first, then matches allowed results.
        Returns a default SandboxResult if no match is found.

        Args:
            code: The Python source code to "execute".
            tools: Ignored in mock implementation.
            resource_limits: Ignored in mock implementation.

        Returns:
            SandboxResult with matched or default output.

        Raises:
            SandboxViolation: If the code contains a denied operation.
        """
        self._execution_count += 1

        # Check denied operations
        for denied in self._denied_operations:
            if denied in code:
                raise SandboxViolation(f"Denied operation detected in code: {denied}")

        # Check allowed results for matching key
        for pattern, result_value in self._allowed_results.items():
            if pattern in code:
                return SandboxResult(
                    output=result_value,
                    return_value=result_value,
                    metrics=ResourceMetrics(
                        cpu_time_ms=1.0,
                        memory_peak_mb=10.0,
                        wall_time_ms=1.0,
                    ),
                )

        # Default result
        return SandboxResult(
            output=None,
            return_value=None,
            metrics=ResourceMetrics(
                cpu_time_ms=0.5,
                memory_peak_mb=5.0,
                wall_time_ms=0.5,
            ),
        )

    async def __aenter__(self) -> MockSandbox:
        """Enter the mock sandbox context."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the mock sandbox context (no-op)."""
