"""Base policy classes for harness evaluation.

Provides the Policy base class and PolicyResult model used by all
concrete policy implementations. Policies evaluate generated code
against configurable constraints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PolicyResult(BaseModel):
    """Result of a policy evaluation.

    Attributes:
        allowed: Whether the code is allowed under this policy.
        violations: List of violation descriptions if not allowed.
        warnings: List of non-blocking warnings.
        policy_name: Name of the policy that produced this result.
    """

    allowed: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    policy_name: str = ""


class Policy(BaseModel):
    """Base class for all harness policies.

    Subclasses implement evaluate() to check generated code against
    their specific constraints. Policies are pure computation (sync,
    no I/O) and must be deterministic for a given input.

    Example:
        class MyPolicy(Policy):
            max_lines: int = 100

            def evaluate(self, *, code: str, **kwargs: Any) -> PolicyResult:
                lines = code.count("\\n") + 1
                if lines > self.max_lines:
                    return PolicyResult(
                        allowed=False,
                        violations=[f"Code has {lines} lines, max is {self.max_lines}"],
                        policy_name="MyPolicy",
                    )
                return PolicyResult(allowed=True, policy_name="MyPolicy")
    """

    model_config = {"extra": "forbid"}

    def evaluate(
        self,
        *,
        code: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Evaluate generated code against this policy.

        Args:
            code: The generated Python source code to evaluate.
            intent_action: The classified action type (read, write, etc.).
            intent_domain: The domain of the request (order, product, etc.).
            **kwargs: Additional context for evaluation.

        Returns:
            PolicyResult indicating whether the code is allowed.
        """
        return PolicyResult(allowed=True, policy_name=self.__class__.__name__)
