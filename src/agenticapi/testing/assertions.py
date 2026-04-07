"""Test assertion helpers for AgenticAPI.

Provides assertion functions for verifying code safety, policy
enforcement, and intent parsing in tests. These raise AssertionError
with descriptive messages on failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agenticapi.exceptions import PolicyViolation
from agenticapi.harness.policy.evaluator import PolicyEvaluator
from agenticapi.harness.sandbox.static_analysis import check_code_safety
from agenticapi.interface.intent import IntentAction, IntentParser

if TYPE_CHECKING:
    from agenticapi.harness.policy.base import Policy


def assert_code_safe(
    code: str,
    *,
    denied_modules: list[str] | None = None,
) -> None:
    """Assert that code passes static safety analysis.

    Runs AST-based static analysis on the provided code and raises
    AssertionError if any safety violations with severity "error"
    are found.

    Args:
        code: Python source code to check.
        denied_modules: Optional list of denied module names.

    Raises:
        AssertionError: If the code has safety violations.
    """
    result = check_code_safety(
        code,
        denied_modules=denied_modules,
        deny_eval_exec=True,
        deny_dynamic_import=True,
    )

    if not result.safe:
        violation_details = "; ".join(
            f"[{v.rule}] {v.description} (line {v.line})" for v in result.violations if v.severity == "error"
        )
        msg = f"Code safety check failed: {violation_details}"
        raise AssertionError(msg)


def assert_policy_enforced(
    code: str,
    policies: list[Policy],
) -> None:
    """Assert that all policies allow the code.

    Evaluates the code against each policy. If any policy denies the
    code, raises AssertionError with violation details.

    Args:
        code: Python source code to evaluate.
        policies: List of policies to check against.

    Raises:
        AssertionError: If any policy denies the code.
    """
    evaluator = PolicyEvaluator(policies=policies)

    try:
        evaluator.evaluate(code=code)
    except PolicyViolation as exc:
        msg = f"Policy enforcement failed: {exc}"
        raise AssertionError(msg) from exc


def assert_intent_parsed(
    raw: str,
    expected_action: IntentAction,
) -> None:
    """Assert that a raw intent string parses to the expected action.

    Uses the keyword-based parser (no LLM) for deterministic testing.

    Args:
        raw: The raw natural language intent string.
        expected_action: The expected IntentAction after parsing.

    Raises:
        AssertionError: If the parsed action does not match expected.
    """
    parser = IntentParser()
    # Use the sync keyword parser directly for deterministic assertion
    intent = parser._parse_with_keywords(raw, {})

    if intent.action != expected_action:
        msg = f"Intent action mismatch: expected {expected_action!r}, got {intent.action!r} for input {raw!r}"
        raise AssertionError(msg)
