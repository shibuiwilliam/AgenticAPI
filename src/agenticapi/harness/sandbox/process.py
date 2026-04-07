"""Process-based sandbox runtime.

Executes generated Python code in an isolated subprocess with
timeout enforcement and output capture. This is the Phase 1
sandbox implementation providing basic process-level isolation.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import tempfile
import time
from typing import Any

import structlog

from agenticapi.exceptions import CodeExecutionError, SandboxViolation
from agenticapi.harness.sandbox.base import (
    ResourceLimits,
    ResourceMetrics,
    SandboxResult,
    SandboxRuntime,
)

logger = structlog.get_logger(__name__)

# Wrapper script that executes the user code and captures the result.
# Uses base64 encoding to safely transport user code, avoiding any
# repr() edge cases or string escaping vulnerabilities.
_WRAPPER_TEMPLATE = """\
import base64
import json
import sys
import traceback

_result = {{"output": None, "return_value": None, "error": None}}

try:
    _code = base64.b64decode("{code_b64}").decode("utf-8")
    _namespace = {{}}
    exec(_code, _namespace)

    # Try to capture a 'result' variable if defined
    if "result" in _namespace:
        _val = _namespace["result"]
        try:
            json.dumps(_val)
            _result["return_value"] = _val
        except (TypeError, ValueError):
            _result["return_value"] = str(_val)

    _result["output"] = "ok"
except Exception as _exc:
    _result["error"] = traceback.format_exc()
    _result["output"] = "error"

print("__SANDBOX_RESULT__")
print(json.dumps(_result))
"""


class ProcessSandbox(SandboxRuntime):
    """Subprocess-based sandbox for executing generated code.

    Runs code in a separate Python subprocess with timeout enforcement.
    Captures stdout/stderr and measures wall-clock execution time.

    This is the Phase 1 implementation. It provides process-level
    isolation but not kernel-level sandboxing. For production
    multi-tenant use, upgrade to ContainerSandbox (Phase 2).

    Example:
        async with ProcessSandbox() as sandbox:
            result = await sandbox.execute(
                code="result = 2 + 2",
                tools=None,
                resource_limits=ResourceLimits(max_execution_time_seconds=10),
            )
            assert result.return_value == 4
    """

    def __init__(self, *, resource_limits: ResourceLimits | None = None) -> None:
        """Initialize the process sandbox.

        Args:
            resource_limits: Default resource limits. Can be overridden
                per-execution in the execute() call.
        """
        self._default_limits = resource_limits or ResourceLimits()

    async def execute(
        self,
        code: str,
        tools: Any = None,
        resource_limits: ResourceLimits | None = None,
    ) -> SandboxResult:
        """Execute code in an isolated subprocess.

        Args:
            code: Python source code to execute.
            tools: ToolRegistry (currently unused in Phase 1).
            resource_limits: Resource limits to enforce. Falls back to
                default limits if not provided.

        Returns:
            SandboxResult with captured output and metrics.

        Raises:
            CodeExecutionError: If the code fails to execute.
            SandboxViolation: If execution times out.
        """
        limits = resource_limits or self._default_limits
        timeout = limits.max_execution_time_seconds

        # Build the wrapper script (base64-encode user code for safe transport)
        code_b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
        wrapper_code = _WRAPPER_TEMPLATE.format(code_b64=code_b64)

        # Write to a temporary file and execute
        start_time = time.monotonic()
        tmp_path: str | None = None

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(wrapper_code)

            process = await asyncio.create_subprocess_exec(
                "python",
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                wall_time = (time.monotonic() - start_time) * 1000
                logger.error("sandbox_timeout", timeout=timeout, wall_time_ms=wall_time)
                raise SandboxViolation(f"Code execution timed out after {timeout} seconds") from exc

        except SandboxViolation:
            raise
        except Exception as exc:
            wall_time = (time.monotonic() - start_time) * 1000
            logger.error("sandbox_execution_failed", error=str(exc), wall_time_ms=wall_time)
            raise CodeExecutionError(f"Sandbox execution failed: {exc}") from exc
        finally:
            # Clean up temp file
            if tmp_path is not None:
                import os

                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

        wall_time = (time.monotonic() - start_time) * 1000
        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")

        # Parse the result from stdout
        output: Any = None
        return_value: Any = None

        if "__SANDBOX_RESULT__" in stdout_str:
            parts = stdout_str.split("__SANDBOX_RESULT__", 1)
            user_stdout = parts[0].rstrip("\n")
            result_json = parts[1].strip()

            try:
                parsed = json.loads(result_json)
                output = parsed.get("output")
                return_value = parsed.get("return_value")
                error = parsed.get("error")

                if error:
                    logger.warning("sandbox_code_error", error=error[:500])
                    raise CodeExecutionError(f"Code execution error:\n{error}")
            except json.JSONDecodeError as json_err:
                logger.warning(
                    "sandbox_result_json_parse_failed",
                    error=str(json_err),
                    result_preview=result_json[:200] if result_json else "",
                )
                user_stdout = stdout_str
        else:
            user_stdout = stdout_str

        # Check return code
        if process.returncode != 0 and output != "error":
            logger.warning(
                "sandbox_nonzero_exit",
                returncode=process.returncode,
                stderr=stderr_str[:500],
            )
            raise CodeExecutionError(f"Subprocess exited with code {process.returncode}: {stderr_str[:500]}")

        metrics = ResourceMetrics(
            cpu_time_ms=0.0,  # Not measurable in basic subprocess mode
            memory_peak_mb=0.0,  # Not measurable in basic subprocess mode
            wall_time_ms=wall_time,
        )

        logger.info("sandbox_execution_complete", wall_time_ms=wall_time, has_return_value=return_value is not None)

        return SandboxResult(
            output=output,
            return_value=return_value,
            metrics=metrics,
            stdout=user_stdout,
            stderr=stderr_str,
        )

    async def __aenter__(self) -> ProcessSandbox:
        """Enter the sandbox context."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the sandbox context."""
