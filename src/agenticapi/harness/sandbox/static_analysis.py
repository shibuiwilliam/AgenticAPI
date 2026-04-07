"""AST-based static safety analysis for generated code.

Parses Python code into an AST and walks all nodes to detect
dangerous patterns before execution. This is the first line of
defense; the sandbox provides runtime isolation as a second layer.

Detected patterns:
    - Import of denied modules (or not in allowed list)
    - eval() / exec() calls
    - __import__() calls
    - Dangerous builtins: compile, globals, locals, vars
    - open() calls (file I/O)
    - Syntax errors in the code
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

# Dangerous builtin functions to flag
_DANGEROUS_BUILTINS: frozenset[str] = frozenset(
    {
        "compile",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "help",
        "getattr",
        "setattr",
        "delattr",
    }
)

# File I/O related function names
_FILE_IO_BUILTINS: frozenset[str] = frozenset(
    {
        "open",
    }
)


@dataclass(frozen=True, slots=True)
class SafetyViolation:
    """A single safety violation detected by static analysis.

    Attributes:
        rule: Identifier for the violated rule.
        description: Human-readable description of the violation.
        line: Line number where the violation was found.
        col: Column offset where the violation was found.
        severity: Severity level ("error" or "warning").
    """

    rule: str
    description: str
    line: int
    col: int
    severity: str  # "error" | "warning"


@dataclass(frozen=True, slots=True)
class SafetyResult:
    """Result of static safety analysis.

    Attributes:
        safe: Whether the code passed all safety checks.
        violations: List of violations found (empty if safe).
    """

    safe: bool
    violations: list[SafetyViolation] = field(default_factory=list)


def check_code_safety(
    code: str,
    *,
    allowed_modules: list[str] | None = None,
    denied_modules: list[str] | None = None,
    deny_eval_exec: bool = True,
    deny_dynamic_import: bool = True,
) -> SafetyResult:
    """Check generated code safety using AST analysis.

    Parses the code into an AST and walks all nodes to detect
    dangerous patterns. Returns a SafetyResult indicating whether
    the code is safe to execute.

    Args:
        code: Python source code to analyze.
        allowed_modules: Whitelist of allowed modules (if provided,
            only these modules may be imported).
        denied_modules: Blacklist of denied modules.
        deny_eval_exec: Whether to flag eval()/exec() as violations.
        deny_dynamic_import: Whether to flag __import__() as violations.

    Returns:
        SafetyResult with safe=True if no violations, or safe=False
        with a list of SafetyViolation objects.
    """
    violations: list[SafetyViolation] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        violations.append(
            SafetyViolation(
                rule="syntax_error",
                description=f"Code has syntax error: {e}",
                line=e.lineno or 0,
                col=e.offset or 0,
                severity="error",
            )
        )
        return SafetyResult(safe=False, violations=violations)

    for node in ast.walk(tree):
        _check_imports(node, violations, allowed_modules=allowed_modules, denied_modules=denied_modules)
        _check_dangerous_calls(node, violations, deny_eval_exec=deny_eval_exec, deny_dynamic_import=deny_dynamic_import)
        _check_dangerous_builtins(node, violations)
        _check_file_io(node, violations)

    has_errors = any(v.severity == "error" for v in violations)
    return SafetyResult(safe=not has_errors, violations=violations)


def _get_line_col(node: ast.AST) -> tuple[int, int]:
    """Extract line and column from an AST node."""
    return getattr(node, "lineno", 0), getattr(node, "col_offset", 0)


def _check_imports(
    node: ast.AST,
    violations: list[SafetyViolation],
    *,
    allowed_modules: list[str] | None,
    denied_modules: list[str] | None,
) -> None:
    """Check import statements for denied or non-allowed modules."""
    module_names: list[str] = []

    if isinstance(node, ast.Import):
        module_names = [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom) and node.module is not None:
        module_names = [node.module]

    line, col = _get_line_col(node)

    for module_name in module_names:
        top_level = module_name.split(".")[0]

        # Check denied modules
        if denied_modules and (top_level in denied_modules or module_name in denied_modules):
            violations.append(
                SafetyViolation(
                    rule="denied_import",
                    description=f"Import of denied module: {module_name}",
                    line=line,
                    col=col,
                    severity="error",
                )
            )
            continue

        # Check allowed modules whitelist
        if allowed_modules is not None and top_level not in allowed_modules and module_name not in allowed_modules:
            violations.append(
                SafetyViolation(
                    rule="unlisted_import",
                    description=f"Import of module not in allowed list: {module_name}",
                    line=line,
                    col=col,
                    severity="error",
                )
            )


def _get_call_name(func: ast.expr) -> str | None:
    """Extract the function name from a call expression.

    Handles both direct calls (eval()) and attribute calls (obj.eval()).

    Args:
        func: The function expression from an ast.Call node.

    Returns:
        The function/method name, or None if it cannot be determined.
    """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _check_dangerous_calls(
    node: ast.AST,
    violations: list[SafetyViolation],
    *,
    deny_eval_exec: bool,
    deny_dynamic_import: bool,
) -> None:
    """Check for eval(), exec(), and __import__() calls.

    Detects both direct calls (eval(...)) and attribute-based calls
    (builtins.eval(...), obj.exec(...)) to prevent bypasses.
    """
    if not isinstance(node, ast.Call):
        return

    name = _get_call_name(node.func)
    if name is None:
        return

    line, col = _get_line_col(node)

    if deny_eval_exec and name in ("eval", "exec"):
        violations.append(
            SafetyViolation(
                rule="eval_exec",
                description=f"Use of {name}() is not allowed",
                line=line,
                col=col,
                severity="error",
            )
        )

    if deny_dynamic_import and name == "__import__":
        violations.append(
            SafetyViolation(
                rule="dynamic_import",
                description="Use of __import__() is not allowed",
                line=line,
                col=col,
                severity="error",
            )
        )


def _check_dangerous_builtins(node: ast.AST, violations: list[SafetyViolation]) -> None:
    """Check for dangerous builtin function calls.

    Detects both direct calls and attribute-based calls.
    """
    if not isinstance(node, ast.Call):
        return

    name = _get_call_name(node.func)
    if name is None:
        return

    if name in _DANGEROUS_BUILTINS:
        line, col = _get_line_col(node)
        violations.append(
            SafetyViolation(
                rule="dangerous_builtin",
                description=f"Use of dangerous builtin {name}() detected",
                line=line,
                col=col,
                severity="warning",
            )
        )


def _check_file_io(node: ast.AST, violations: list[SafetyViolation]) -> None:
    """Check for file I/O operations.

    Detects both direct calls and attribute-based calls.
    """
    if not isinstance(node, ast.Call):
        return

    name = _get_call_name(node.func)
    if name is None:
        return

    if name in _FILE_IO_BUILTINS:
        line, col = _get_line_col(node)
        violations.append(
            SafetyViolation(
                rule="file_io",
                description=f"Use of {name}() for file I/O is not allowed",
                line=line,
                col=col,
                severity="error",
            )
        )
