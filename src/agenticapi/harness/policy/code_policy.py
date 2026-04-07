"""Code policy for validating generated Python code.

Uses AST parsing to check imports, eval/exec calls, dynamic imports,
and other potentially dangerous patterns against configurable restrictions.
"""

from __future__ import annotations

import ast
from typing import Any

from pydantic import Field

from agenticapi.harness.policy.base import Policy, PolicyResult

# Default set of dangerous modules
_DEFAULT_DENIED_MODULES: list[str] = [
    "os",
    "subprocess",
    "shutil",
    "importlib",
    "sys",
]

# Modules that indicate network access
_NETWORK_MODULES: list[str] = [
    "socket",
    "urllib",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "telnetlib",
]


class CodePolicy(Policy):
    """Policy that validates generated code against module and pattern restrictions.

    Uses AST parsing to detect dangerous patterns such as forbidden imports,
    eval/exec usage, dynamic imports, and network access.

    Attributes:
        allowed_modules: Whitelist of allowed modules (empty = no whitelist filtering).
        denied_modules: Blacklist of denied modules.
        max_code_lines: Maximum number of lines allowed in generated code.
        deny_eval_exec: Whether to deny eval() and exec() calls.
        deny_dynamic_import: Whether to deny __import__() calls.
        allow_network: Whether to allow network-related modules.
        allowed_hosts: Whitelist of allowed hosts (unused in static analysis).
    """

    allowed_modules: list[str] = Field(default_factory=list)
    denied_modules: list[str] = Field(default_factory=lambda: list(_DEFAULT_DENIED_MODULES))
    max_code_lines: int = Field(default=500, ge=1)
    deny_eval_exec: bool = True
    deny_dynamic_import: bool = True
    allow_network: bool = False
    allowed_hosts: list[str] = Field(default_factory=list)

    def evaluate(self, *, code: str, **kwargs: Any) -> PolicyResult:
        """Evaluate generated code against code restrictions.

        Args:
            code: The generated Python source code.
            **kwargs: Additional context (ignored).

        Returns:
            PolicyResult with any violations found.
        """
        violations: list[str] = []
        warnings: list[str] = []

        # Check line count
        line_count = code.count("\n") + 1
        if line_count > self.max_code_lines:
            violations.append(f"Code has {line_count} lines, exceeds maximum of {self.max_code_lines}")

        # Parse AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            violations.append(f"Code has syntax error: {e}")
            return PolicyResult(
                allowed=False,
                violations=violations,
                warnings=warnings,
                policy_name="CodePolicy",
            )

        # Walk AST nodes
        for node in ast.walk(tree):
            self._check_imports(node, violations, warnings)
            self._check_eval_exec(node, violations)
            self._check_dynamic_import(node, violations)

        allowed = len(violations) == 0
        return PolicyResult(
            allowed=allowed,
            violations=violations,
            warnings=warnings,
            policy_name="CodePolicy",
        )

    def _check_imports(
        self,
        node: ast.AST,
        violations: list[str],
        warnings: list[str],
    ) -> None:
        """Check import statements against allowed/denied module lists."""
        module_names: list[str] = []

        if isinstance(node, ast.Import):
            module_names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            module_names = [node.module]

        for module_name in module_names:
            # Get the top-level module name
            top_level = module_name.split(".")[0]

            # Check denied modules
            if top_level in self.denied_modules or module_name in self.denied_modules:
                violations.append(f"Import of denied module: {module_name}")
                continue

            # Check network modules
            if not self.allow_network and top_level in _NETWORK_MODULES:
                violations.append(f"Import of network module not allowed: {module_name}")
                continue

            # Check allowed modules whitelist
            if (
                self.allowed_modules
                and top_level not in self.allowed_modules
                and module_name not in self.allowed_modules
            ):
                violations.append(f"Import of module not in allowed list: {module_name}")

    def _check_eval_exec(self, node: ast.AST, violations: list[str]) -> None:
        """Check for eval() and exec() calls."""
        if not self.deny_eval_exec:
            return

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                violations.append(f"Use of {func.id}() is denied")

    def _check_dynamic_import(self, node: ast.AST, violations: list[str]) -> None:
        """Check for __import__() calls."""
        if not self.deny_dynamic_import:
            return

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                violations.append("Use of __import__() is denied")
