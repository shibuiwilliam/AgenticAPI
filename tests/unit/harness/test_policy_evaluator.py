"""Tests for PolicyEvaluator."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import PolicyViolation
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.harness.policy.evaluator import PolicyEvaluator


class TestPolicyEvaluatorNoPolicies:
    def test_no_policies_passes(self) -> None:
        evaluator = PolicyEvaluator()
        result = evaluator.evaluate(code="x = 1")
        assert result.allowed is True
        assert result.violations == []

    def test_empty_list_passes(self) -> None:
        evaluator = PolicyEvaluator(policies=[])
        result = evaluator.evaluate(code="x = 1")
        assert result.allowed is True


class TestPolicyEvaluatorSinglePolicy:
    def test_passing_policy(self) -> None:
        policy = CodePolicy(denied_modules=[])
        evaluator = PolicyEvaluator(policies=[policy])
        result = evaluator.evaluate(code="x = 1")
        assert result.allowed is True

    def test_failing_policy_raises(self) -> None:
        policy = CodePolicy(denied_modules=["os"])
        evaluator = PolicyEvaluator(policies=[policy])
        with pytest.raises(PolicyViolation, match="os"):
            evaluator.evaluate(code="import os")


class TestPolicyEvaluatorMultiplePolicies:
    def test_all_pass(self) -> None:
        policies = [
            CodePolicy(denied_modules=[]),
            DataPolicy(deny_ddl=True),
        ]
        evaluator = PolicyEvaluator(policies=policies)
        result = evaluator.evaluate(code="x = 1")
        assert result.allowed is True
        assert len(result.results) == 2

    def test_one_fails_raises(self) -> None:
        policies = [
            CodePolicy(denied_modules=["os"]),
            DataPolicy(deny_ddl=True),
        ]
        evaluator = PolicyEvaluator(policies=policies)
        with pytest.raises(PolicyViolation):
            evaluator.evaluate(code="import os")

    def test_aggregated_violations(self) -> None:
        policies = [
            CodePolicy(denied_modules=["os"]),
            DataPolicy(deny_ddl=True),
        ]
        evaluator = PolicyEvaluator(policies=policies)
        code = "import os\ndb.execute('DROP TABLE users')"
        with pytest.raises(PolicyViolation) as exc_info:
            evaluator.evaluate(code=code)
        # Both violations should be mentioned
        assert "os" in str(exc_info.value)
        assert "DDL" in str(exc_info.value)


class TestPolicyEvaluatorAddPolicy:
    def test_add_policy_dynamically(self) -> None:
        evaluator = PolicyEvaluator()
        assert len(evaluator.policies) == 0
        evaluator.add_policy(CodePolicy(denied_modules=["os"]))
        assert len(evaluator.policies) == 1
        with pytest.raises(PolicyViolation):
            evaluator.evaluate(code="import os")


class TestPolicyEvaluatorPolicyViolationAttributes:
    def test_violation_has_generated_code(self) -> None:
        evaluator = PolicyEvaluator(policies=[CodePolicy(denied_modules=["os"])])
        with pytest.raises(PolicyViolation) as exc_info:
            evaluator.evaluate(code="import os")
        assert exc_info.value.generated_code == "import os"

    def test_violation_has_policy_name(self) -> None:
        evaluator = PolicyEvaluator(policies=[CodePolicy(denied_modules=["os"])])
        with pytest.raises(PolicyViolation) as exc_info:
            evaluator.evaluate(code="import os")
        assert "CodePolicy" in exc_info.value.policy
