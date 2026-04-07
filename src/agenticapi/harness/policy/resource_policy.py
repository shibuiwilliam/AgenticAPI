"""Resource policy for limiting computational resources.

Stores resource limits and performs basic complexity checks on
generated code to flag potential resource-intensive operations.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from pydantic import Field

from agenticapi.harness.policy.base import Policy, PolicyResult

# Patterns that suggest potentially expensive operations
_NESTED_LOOP_DEPTH_THRESHOLD = 3
_LARGE_COLLECTION_PATTERN = re.compile(r"\brange\s*\(\s*(\d+)\s*\)", re.IGNORECASE)
_LARGE_RANGE_THRESHOLD = 1_000_000


class ResourcePolicy(Policy):
    """Policy that enforces resource limits on generated code.

    Primarily stores resource limits for sandbox enforcement, but also
    performs basic static checks for obviously resource-intensive patterns.

    Attributes:
        max_cpu_seconds: Maximum CPU time in seconds.
        max_memory_mb: Maximum memory usage in megabytes.
        max_execution_time_seconds: Maximum wall-clock execution time.
        max_concurrent_operations: Maximum concurrent operations.
        max_cost_per_request_usd: Maximum estimated cost per request.
    """

    max_cpu_seconds: float = Field(default=30.0, gt=0)
    max_memory_mb: int = Field(default=512, ge=1)
    max_execution_time_seconds: float = Field(default=60.0, gt=0)
    max_concurrent_operations: int = Field(default=10, ge=1)
    max_cost_per_request_usd: float = Field(default=0.50, ge=0)

    def evaluate(self, *, code: str, **kwargs: Any) -> PolicyResult:
        """Evaluate generated code for resource-intensive patterns.

        Performs basic static analysis to detect obviously expensive
        operations like deeply nested loops or very large ranges.

        Args:
            code: The generated Python source code.
            **kwargs: Additional context (ignored).

        Returns:
            PolicyResult with any violations or warnings found.
        """
        violations: list[str] = []
        warnings: list[str] = []

        self._check_loop_depth(code, violations, warnings)
        self._check_large_ranges(code, violations, warnings)
        self._check_recursive_patterns(code, warnings)

        allowed = len(violations) == 0
        return PolicyResult(
            allowed=allowed,
            violations=violations,
            warnings=warnings,
            policy_name="ResourcePolicy",
        )

    def _check_loop_depth(self, code: str, violations: list[str], warnings: list[str]) -> None:
        """Check for deeply nested loops that may indicate O(n^k) complexity."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return

        max_depth = _find_max_loop_depth(tree)
        if max_depth >= _NESTED_LOOP_DEPTH_THRESHOLD:
            violations.append(
                f"Deeply nested loops detected (depth {max_depth}). "
                f"Maximum allowed nesting depth is {_NESTED_LOOP_DEPTH_THRESHOLD - 1}."
            )
        elif max_depth >= 2:
            warnings.append(f"Nested loops detected (depth {max_depth}). May be resource-intensive.")

    def _check_large_ranges(self, code: str, violations: list[str], warnings: list[str]) -> None:
        """Check for very large range() calls."""
        matches = _LARGE_COLLECTION_PATTERN.findall(code)
        for match in matches:
            try:
                value = int(match)
                if value >= _LARGE_RANGE_THRESHOLD:
                    violations.append(
                        f"Very large range({value}) detected. Maximum allowed range size is {_LARGE_RANGE_THRESHOLD}."
                    )
            except ValueError:
                pass

    def _check_recursive_patterns(self, code: str, warnings: list[str]) -> None:
        """Check for potential recursive function calls."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                func_name = node.name
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == func_name:
                        warnings.append(
                            f"Recursive function '{func_name}' detected. Ensure it has proper termination conditions."
                        )
                        break


def _find_max_loop_depth(tree: ast.AST) -> int:
    """Find the maximum nesting depth of for/while loops in an AST.

    Args:
        tree: The AST to analyze.

    Returns:
        Maximum loop nesting depth found.
    """

    def _walk_depth(node: ast.AST, current_depth: int) -> int:
        max_depth = current_depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.For | ast.While | ast.AsyncFor):
                child_depth = _walk_depth(child, current_depth + 1)
            else:
                child_depth = _walk_depth(child, current_depth)
            max_depth = max(max_depth, child_depth)
        return max_depth

    return _walk_depth(tree, 0)
