"""Runtime policy for dynamic evaluation at request time.

Evaluates constraints that depend on runtime context such as code
complexity. Rate limiting and authentication checks are deferred
to middleware (Phase 2).
"""

from __future__ import annotations

import ast
from typing import Any

import structlog
from pydantic import Field

from agenticapi.harness.policy.base import Policy, PolicyResult

logger = structlog.get_logger(__name__)


class RuntimePolicy(Policy):
    """Dynamic policy evaluation for runtime constraints.

    Checks code complexity via AST node count and enforces configurable
    limits. Future versions will integrate with middleware for rate
    limiting and authentication.

    Example:
        policy = RuntimePolicy(max_code_complexity=500)
        result = policy.evaluate(code="x = 1")
        assert result.allowed is True
    """

    max_code_complexity: int = Field(
        default=500,
        ge=1,
        description="Maximum AST node count (proxy for code complexity).",
    )
    max_code_lines: int = Field(
        default=500,
        ge=1,
        description="Maximum number of lines in generated code.",
    )

    def evaluate(
        self,
        *,
        code: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Evaluate runtime constraints on the generated code.

        Checks:
        - Code complexity via AST node count
        - Code length (line count)

        Args:
            code: The generated Python source code.
            intent_action: The classified action type.
            intent_domain: The domain of the request.
            **kwargs: Additional context.

        Returns:
            PolicyResult indicating whether the code passes runtime checks.
        """
        violations: list[str] = []
        warnings: list[str] = []

        # Check line count
        line_count = code.count("\n") + 1
        if line_count > self.max_code_lines:
            violations.append(f"Code has {line_count} lines, exceeds maximum of {self.max_code_lines}")

        # Check complexity via AST node count
        try:
            tree = ast.parse(code)
            node_count = sum(1 for _ in ast.walk(tree))
            if node_count > self.max_code_complexity:
                violations.append(
                    f"Code complexity ({node_count} AST nodes) exceeds maximum of {self.max_code_complexity}"
                )
            elif node_count > self.max_code_complexity * 0.8:
                warnings.append(
                    f"Code complexity ({node_count} AST nodes) approaching limit of {self.max_code_complexity}"
                )
        except SyntaxError:
            violations.append("Code contains syntax errors and cannot be analyzed")

        allowed = len(violations) == 0

        if not allowed:
            logger.warning(
                "runtime_policy_violation",
                violations=violations,
                line_count=line_count,
            )

        return PolicyResult(
            allowed=allowed,
            violations=violations,
            warnings=warnings,
            policy_name="RuntimePolicy",
        )
