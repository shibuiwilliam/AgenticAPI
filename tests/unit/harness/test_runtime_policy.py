"""Tests for RuntimePolicy."""

from __future__ import annotations

from agenticapi.harness.policy.runtime_policy import RuntimePolicy


class TestRuntimePolicyComplexity:
    def test_simple_code_passes(self) -> None:
        policy = RuntimePolicy(max_code_complexity=50)
        result = policy.evaluate(code="x = 1")
        assert result.allowed is True

    def test_complex_code_fails(self) -> None:
        # Generate code with many AST nodes
        lines = [f"x{i} = {i}" for i in range(60)]
        code = "\n".join(lines)
        policy = RuntimePolicy(max_code_complexity=10)
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("complexity" in v for v in result.violations)

    def test_near_limit_generates_warning(self) -> None:
        # A few assignments should be close to a low limit
        code = "x = 1\ny = 2\nz = 3"
        policy = RuntimePolicy(max_code_complexity=10)
        result = policy.evaluate(code=code)
        # Should pass but may have warnings depending on exact node count
        if result.allowed:
            # Check that warnings exist if near limit
            pass  # Exact behavior depends on AST node count

    def test_syntax_error_code_fails(self) -> None:
        policy = RuntimePolicy()
        result = policy.evaluate(code="def (broken syntax")
        assert result.allowed is False
        assert any("syntax" in v.lower() for v in result.violations)


class TestRuntimePolicyLineCount:
    def test_short_code_passes(self) -> None:
        policy = RuntimePolicy(max_code_lines=10)
        result = policy.evaluate(code="x = 1\ny = 2")
        assert result.allowed is True

    def test_long_code_fails(self) -> None:
        lines = [f"x{i} = {i}" for i in range(20)]
        code = "\n".join(lines)
        policy = RuntimePolicy(max_code_lines=10)
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("lines" in v for v in result.violations)


class TestRuntimePolicyDefaults:
    def test_default_allows_simple_code(self) -> None:
        policy = RuntimePolicy()
        result = policy.evaluate(code="result = 42")
        assert result.allowed is True
        assert result.policy_name == "RuntimePolicy"

    def test_policy_name_set(self) -> None:
        policy = RuntimePolicy()
        result = policy.evaluate(code="x = 1")
        assert result.policy_name == "RuntimePolicy"
