"""Tests for ProcessSandbox."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import CodeExecutionError, SandboxViolation
from agenticapi.harness.sandbox.base import ResourceLimits
from agenticapi.harness.sandbox.process import ProcessSandbox


class TestProcessSandboxExecution:
    async def test_simple_code(self) -> None:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code="result = 2 + 2",
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert result.return_value == 4
        assert result.output == "ok"

    async def test_capture_stdout(self) -> None:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code="print('hello world')",
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert "hello world" in result.stdout

    async def test_return_value_string(self) -> None:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code='result = "success"',
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert result.return_value == "success"

    async def test_return_value_list(self) -> None:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code="result = [1, 2, 3]",
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert result.return_value == [1, 2, 3]

    async def test_no_result_variable(self) -> None:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code="x = 42",
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert result.return_value is None
        assert result.output == "ok"


class TestProcessSandboxTimeout:
    async def test_timeout_raises(self) -> None:
        async with ProcessSandbox() as sandbox:
            with pytest.raises(SandboxViolation, match="timed out"):
                await sandbox.execute(
                    code="import time; time.sleep(10)",
                    tools=None,
                    resource_limits=ResourceLimits(max_execution_time_seconds=1),
                )


class TestProcessSandboxErrors:
    async def test_runtime_error_raises(self) -> None:
        async with ProcessSandbox() as sandbox:
            with pytest.raises(CodeExecutionError):
                await sandbox.execute(
                    code="raise ValueError('bad')",
                    tools=None,
                    resource_limits=ResourceLimits(),
                )


class TestProcessSandboxMetrics:
    async def test_metrics_populated(self) -> None:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code="result = 1",
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert result.metrics.wall_time_ms > 0


class TestProcessSandboxStderr:
    async def test_stderr_captured(self) -> None:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code="import sys; sys.stderr.write('warning message')\nresult = 1",
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert "warning message" in result.stderr
        assert result.return_value == 1

    async def test_stderr_empty_on_clean_execution(self) -> None:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code="result = 42",
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert result.stderr == ""


class TestProcessSandboxTempFileCleanup:
    async def test_temp_file_cleaned_up(self) -> None:
        """Verify temporary Python file is deleted after execution."""
        import glob
        import tempfile

        tmp_dir = tempfile.gettempdir()
        before = set(glob.glob(f"{tmp_dir}/tmp*.py"))

        async with ProcessSandbox() as sandbox:
            await sandbox.execute(
                code="result = 1",
                tools=None,
                resource_limits=ResourceLimits(),
            )

        after = set(glob.glob(f"{tmp_dir}/tmp*.py"))
        # No new temp .py files should remain
        new_files = after - before
        assert len(new_files) == 0


class TestProcessSandboxBase64Safety:
    async def test_code_with_quotes_executes(self) -> None:
        """Code containing all quote types should execute safely via base64."""
        code = """result = "single: ' double: \\" triple: '''"  """
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code=code,
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert result.return_value is not None

    async def test_code_with_backslashes(self) -> None:
        """Code with backslashes should not break the wrapper."""
        code = r'result = "path\\to\\file"'
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code=code,
                tools=None,
                resource_limits=ResourceLimits(),
            )
        assert result.return_value is not None


class TestProcessSandboxContextManager:
    async def test_aenter_aexit(self) -> None:
        sandbox = ProcessSandbox()
        async with sandbox as s:
            assert s is sandbox
