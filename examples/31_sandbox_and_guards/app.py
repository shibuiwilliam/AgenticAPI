"""Sandbox & Guards example: defence-in-depth code execution.

Demonstrates AgenticAPI's **seven-layer defence model** for executing
generated Python code — from AST-level static analysis through
process-isolated sandbox execution to post-execution monitors and
validators.  No other example in the suite focuses on these safety
primitives directly.

Features demonstrated:

- **``check_code_safety()``** — AST-based static analysis that rejects
  ``eval``, ``exec``, ``open``, ``__import__``, denied modules, and
  dangerous builtins *before* any code runs.
- **``ProcessSandbox``** — subprocess-based execution with wall-clock
  timeout and base64-encoded code transport.
- **``ResourceLimits``** — per-execution CPU / memory / time ceilings.
- **``ResourceMonitor``** — post-execution check that metrics stayed
  within limits.
- **``OutputSizeMonitor``** — post-execution check that output didn't
  blow the memory budget.
- **``OutputTypeValidator``** — ensures return values are
  JSON-serialisable.
- **``ReadOnlyValidator``** — flags SQL write patterns in read-only
  operations.
- **``HarnessEngine``** with ``monitors=`` and ``validators=``
  — shows the harness engine wiring these together.

Run with::

    uvicorn examples.31_sandbox_and_guards.app:app --reload

Test with curl::

    # Safe arithmetic code → passes all layers
    curl -X POST http://127.0.0.1:8000/agent/sandbox.run \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "result = 2 + 2"}'

    # Code with eval() → blocked by static analysis
    curl -X POST http://127.0.0.1:8000/agent/sandbox.run \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "result = eval(\"1+1\")"}'

    # Analyse code without running it
    curl -X POST http://127.0.0.1:8000/agent/sandbox.analyze \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "import os; os.system(\"ls\")"}'

    # Inspect the guard configuration
    curl -X POST http://127.0.0.1:8000/agent/sandbox.guards \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "show guards"}'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi import AgenticApp, HarnessEngine
from agenticapi.harness.sandbox.base import ResourceLimits, SandboxResult
from agenticapi.harness.sandbox.monitors import MonitorResult, OutputSizeMonitor, ResourceMonitor
from agenticapi.harness.sandbox.process import ProcessSandbox
from agenticapi.harness.sandbox.static_analysis import SafetyResult, check_code_safety
from agenticapi.harness.sandbox.validators import OutputTypeValidator, ReadOnlyValidator, ValidationResult

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# Safety configuration
# ---------------------------------------------------------------------------

RESOURCE_LIMITS = ResourceLimits(
    max_cpu_seconds=5.0,
    max_memory_mb=128,
    max_execution_time_seconds=10.0,
)

MAX_OUTPUT_BYTES = 100_000  # 100 KB

# Modules allowed in executed code (whitelist approach)
ALLOWED_MODULES = ["math", "json", "datetime", "collections", "itertools", "statistics"]

# ---------------------------------------------------------------------------
# Monitors and validators
# ---------------------------------------------------------------------------

resource_monitor = ResourceMonitor(limits=RESOURCE_LIMITS)
output_size_monitor = OutputSizeMonitor(max_output_bytes=MAX_OUTPUT_BYTES)
output_type_validator = OutputTypeValidator()
read_only_validator = ReadOnlyValidator()

# ---------------------------------------------------------------------------
# Harness engine with monitors and validators
# ---------------------------------------------------------------------------

harness = HarnessEngine(
    policies=[],
    monitors=[resource_monitor, output_size_monitor],
    validators=[output_type_validator, read_only_validator],
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Sandbox & Guards",
    description=(
        "Defence-in-depth code execution: static analysis, process sandbox, runtime monitors, and output validators."
    ),
    harness=harness,
)


# ---------------------------------------------------------------------------
# Endpoint 1: Run code through all layers
# ---------------------------------------------------------------------------


@app.agent_endpoint(
    name="sandbox.run",
    description="Execute Python code through the full safety stack",
)
async def run_code(intent: Any, context: AgentContext) -> dict[str, Any]:
    """Execute user-supplied code through all seven defence layers.

    1. Static analysis (AST) — reject dangerous patterns
    2. Process sandbox — isolated subprocess with timeout
    3. Resource monitor — check CPU / memory / time
    4. Output size monitor — check output size
    5. Output type validator — ensure JSON-serialisable
    6. Read-only validator — flag write patterns
    """
    code = intent.raw.strip()
    if not code:
        return {"ok": False, "error": "Empty code", "layers": []}

    layers: list[dict[str, Any]] = []

    # --- Layer 1: Static analysis ---
    safety: SafetyResult = check_code_safety(
        code,
        allowed_modules=ALLOWED_MODULES,
        deny_eval_exec=True,
        deny_dynamic_import=True,
    )
    layers.append(
        {
            "layer": "static_analysis",
            "passed": safety.safe,
            "violations": [
                {
                    "rule": v.rule,
                    "description": v.description,
                    "line": v.line,
                    "severity": v.severity,
                }
                for v in safety.violations
            ],
        }
    )

    if not safety.safe:
        return {
            "ok": False,
            "error": "Blocked by static analysis",
            "layers": layers,
            "result": None,
            "metrics": None,
        }

    # --- Layer 2: Sandbox execution ---
    sandbox_result: SandboxResult | None = None
    try:
        async with ProcessSandbox(resource_limits=RESOURCE_LIMITS) as sandbox:
            sandbox_result = await sandbox.execute(
                code=code,
                tools=None,
                resource_limits=RESOURCE_LIMITS,
            )
        layers.append(
            {
                "layer": "sandbox_execution",
                "passed": True,
                "wall_time_ms": round(sandbox_result.metrics.wall_time_ms, 2),
                "stdout_preview": sandbox_result.stdout[:200] if sandbox_result.stdout else "",
            }
        )
    except Exception as exc:
        layers.append(
            {
                "layer": "sandbox_execution",
                "passed": False,
                "error": str(exc)[:300],
            }
        )
        return {
            "ok": False,
            "error": f"Sandbox execution failed: {exc}",
            "layers": layers,
            "result": None,
            "metrics": None,
        }

    # --- Layer 3: Resource monitor ---
    resource_check: MonitorResult = await resource_monitor.on_execution_complete(
        sandbox_result,
        code=code,
    )
    layers.append(
        {
            "layer": "resource_monitor",
            "passed": resource_check.passed,
            "warnings": resource_check.warnings,
            "violations": resource_check.violations,
        }
    )

    # --- Layer 4: Output size monitor ---
    size_check: MonitorResult = await output_size_monitor.on_execution_complete(
        sandbox_result,
        code=code,
    )
    layers.append(
        {
            "layer": "output_size_monitor",
            "passed": size_check.passed,
            "warnings": size_check.warnings,
            "violations": size_check.violations,
        }
    )

    # --- Layer 5: Output type validator ---
    type_check: ValidationResult = await output_type_validator.validate(
        sandbox_result,
        code=code,
        intent_action="read",
    )
    layers.append(
        {
            "layer": "output_type_validator",
            "passed": type_check.valid,
            "errors": type_check.errors,
            "warnings": type_check.warnings,
        }
    )

    # --- Layer 6: Read-only validator ---
    readonly_check: ValidationResult = await read_only_validator.validate(
        sandbox_result,
        code=code,
        intent_action="read",
    )
    layers.append(
        {
            "layer": "read_only_validator",
            "passed": readonly_check.valid,
            "errors": readonly_check.errors,
            "warnings": readonly_check.warnings,
        }
    )

    all_passed = all(layer["passed"] for layer in layers)
    metrics = {
        "wall_time_ms": round(sandbox_result.metrics.wall_time_ms, 2),
        "cpu_time_ms": round(sandbox_result.metrics.cpu_time_ms, 2),
        "memory_peak_mb": round(sandbox_result.metrics.memory_peak_mb, 2),
    }

    return {
        "ok": all_passed,
        "error": None if all_passed else "One or more guards failed",
        "layers": layers,
        "result": sandbox_result.return_value,
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# Endpoint 2: Static analysis only (no execution)
# ---------------------------------------------------------------------------


@app.agent_endpoint(
    name="sandbox.analyze",
    description="Analyse code safety without executing it",
)
async def analyze_code(intent: Any, context: AgentContext) -> dict[str, Any]:
    """Run AST-based static analysis on the submitted code.

    Returns the safety verdict and all detected violations with
    their line numbers and severity levels.
    """
    code = intent.raw.strip()
    if not code:
        return {"safe": False, "error": "Empty code", "violations": []}

    safety = check_code_safety(
        code,
        allowed_modules=ALLOWED_MODULES,
        deny_eval_exec=True,
        deny_dynamic_import=True,
    )

    return {
        "safe": safety.safe,
        "violation_count": len(safety.violations),
        "violations": [
            {
                "rule": v.rule,
                "description": v.description,
                "line": v.line,
                "col": v.col,
                "severity": v.severity,
            }
            for v in safety.violations
        ],
        "allowed_modules": ALLOWED_MODULES,
    }


# ---------------------------------------------------------------------------
# Endpoint 3: Guard configuration
# ---------------------------------------------------------------------------


@app.agent_endpoint(
    name="sandbox.guards",
    description="Inspect the active guard configuration",
)
async def show_guards(intent: Any, context: AgentContext) -> dict[str, Any]:
    """Return the current guard configuration for introspection."""
    return {
        "resource_limits": {
            "max_cpu_seconds": RESOURCE_LIMITS.max_cpu_seconds,
            "max_memory_mb": RESOURCE_LIMITS.max_memory_mb,
            "max_execution_time_seconds": RESOURCE_LIMITS.max_execution_time_seconds,
        },
        "output_limits": {
            "max_output_bytes": MAX_OUTPUT_BYTES,
        },
        "static_analysis": {
            "allowed_modules": ALLOWED_MODULES,
            "deny_eval_exec": True,
            "deny_dynamic_import": True,
        },
        "monitors": ["ResourceMonitor", "OutputSizeMonitor"],
        "validators": ["OutputTypeValidator", "ReadOnlyValidator"],
        "layers": [
            "1. Static analysis (AST) — reject eval/exec/open/__import__/denied modules",
            "2. Process sandbox — isolated subprocess with timeout enforcement",
            "3. Resource monitor — post-execution CPU/memory/time check",
            "4. Output size monitor — post-execution output size check",
            "5. Output type validator — JSON-serialisability check",
            "6. Read-only validator — SQL write pattern detection",
        ],
    }
