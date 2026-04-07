"""Policy evaluator that runs all policies against generated code.

Aggregates results from multiple policies and raises PolicyViolation
if any policy denies the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import PolicyViolation

if TYPE_CHECKING:
    from agenticapi.harness.policy.base import Policy, PolicyResult

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Aggregated result from evaluating all policies.

    Attributes:
        allowed: Whether all policies allowed the code.
        results: Individual results from each policy.
        violations: Aggregated list of all violations across policies.
        warnings: Aggregated list of all warnings across policies.
    """

    allowed: bool
    results: list[PolicyResult]
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PolicyEvaluator:
    """Evaluates generated code against a collection of policies.

    Runs all registered policies and aggregates results. If any policy
    returns allowed=False, the overall result is not allowed and a
    PolicyViolation is raised.

    Example:
        evaluator = PolicyEvaluator(policies=[
            CodePolicy(denied_modules=["os"]),
            DataPolicy(deny_ddl=True),
        ])
        result = evaluator.evaluate(code="SELECT 1", intent_action="read")
    """

    def __init__(self, policies: list[Policy] | None = None) -> None:
        """Initialize the evaluator with optional policies.

        Args:
            policies: Initial list of policies to evaluate against.
        """
        self._policies: list[Policy] = list(policies) if policies else []

    def add_policy(self, policy: Policy) -> None:
        """Add a policy to the evaluator.

        Args:
            policy: The policy to add.
        """
        self._policies.append(policy)
        logger.info("policy_added", policy_type=type(policy).__name__)

    def evaluate(
        self,
        *,
        code: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> EvaluationResult:
        """Evaluate code against all registered policies.

        Runs every policy and aggregates results. If any policy denies
        the code, raises PolicyViolation with all violations.

        Args:
            code: The generated Python source code to evaluate.
            intent_action: The classified action type.
            intent_domain: The domain of the request.
            **kwargs: Additional context passed to each policy.

        Returns:
            EvaluationResult with aggregated results.

        Raises:
            PolicyViolation: If any policy denies the code.
        """
        results: list[PolicyResult] = []
        all_violations: list[str] = []
        all_warnings: list[str] = []
        overall_allowed = True

        for policy in self._policies:
            policy_name = type(policy).__name__
            logger.debug("policy_evaluation_start", policy=policy_name)

            result = policy.evaluate(
                code=code,
                intent_action=intent_action,
                intent_domain=intent_domain,
                **kwargs,
            )
            results.append(result)

            if not result.allowed:
                overall_allowed = False
                all_violations.extend(result.violations)
                logger.warning(
                    "policy_denied",
                    policy=policy_name,
                    violations=result.violations,
                )
            else:
                logger.debug("policy_allowed", policy=policy_name)

            all_warnings.extend(result.warnings)

        if all_warnings:
            logger.info("policy_warnings", warnings=all_warnings)

        evaluation = EvaluationResult(
            allowed=overall_allowed,
            results=results,
            violations=all_violations,
            warnings=all_warnings,
        )

        if not overall_allowed:
            violation_summary = "; ".join(all_violations)
            policy_names = ", ".join(r.policy_name for r in results if not r.allowed)
            raise PolicyViolation(
                policy=policy_names,
                violation=violation_summary,
                generated_code=code,
            )

        return evaluation

    @property
    def policies(self) -> list[Policy]:
        """Return a copy of the registered policies."""
        return list(self._policies)
