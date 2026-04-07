"""Benchmark: ProcessSandbox startup and trivial execution.

Target: < 100ms for startup + trivial execution.
"""

from __future__ import annotations

import asyncio

import pytest

from agenticapi.harness.sandbox.base import ResourceLimits
from agenticapi.harness.sandbox.process import ProcessSandbox


def _run_sandbox() -> None:
    """Run a trivial sandbox execution synchronously."""

    async def _execute() -> None:
        async with ProcessSandbox() as sandbox:
            await sandbox.execute(
                code="result = 1 + 1",
                tools=None,
                resource_limits=ResourceLimits(),
            )

    asyncio.run(_execute())


@pytest.mark.benchmark
def test_bench_sandbox_startup_and_execution(benchmark) -> None:  # type: ignore[no-untyped-def]
    """Benchmark sandbox startup + trivial code execution."""
    benchmark.pedantic(_run_sandbox, rounds=5, warmup_rounds=1)
    assert benchmark.stats["mean"] < 0.100  # 100ms
