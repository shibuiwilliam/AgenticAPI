"""Tests for CodePolicy."""

from __future__ import annotations

from agenticapi.harness.policy.code_policy import CodePolicy


class TestCodePolicyDeniedModules:
    def test_denies_os_import(self) -> None:
        policy = CodePolicy(denied_modules=["os"])
        result = policy.evaluate(code="import os")
        assert result.allowed is False
        assert any("os" in v for v in result.violations)

    def test_denies_subprocess_import(self) -> None:
        policy = CodePolicy(denied_modules=["subprocess"])
        result = policy.evaluate(code="import subprocess")
        assert result.allowed is False
        assert any("subprocess" in v for v in result.violations)

    def test_denies_from_import(self) -> None:
        policy = CodePolicy(denied_modules=["os"])
        result = policy.evaluate(code="from os.path import join")
        assert result.allowed is False

    def test_allows_safe_imports(self) -> None:
        policy = CodePolicy(denied_modules=["os", "subprocess"])
        result = policy.evaluate(code="import json\nimport math")
        assert result.allowed is True
        assert result.violations == []

    def test_default_denied_modules(self) -> None:
        policy = CodePolicy()
        result = policy.evaluate(code="import os")
        assert result.allowed is False


class TestCodePolicyEvalExec:
    def test_deny_eval(self) -> None:
        policy = CodePolicy(denied_modules=[])
        result = policy.evaluate(code="x = eval('1+1')")
        assert result.allowed is False
        assert any("eval" in v for v in result.violations)

    def test_deny_exec(self) -> None:
        policy = CodePolicy(denied_modules=[])
        result = policy.evaluate(code="exec('print(1)')")
        assert result.allowed is False
        assert any("exec" in v for v in result.violations)

    def test_allow_eval_when_disabled(self) -> None:
        policy = CodePolicy(denied_modules=[], deny_eval_exec=False)
        result = policy.evaluate(code="x = eval('1+1')")
        assert result.allowed is True


class TestCodePolicyDynamicImport:
    def test_deny_dunder_import(self) -> None:
        policy = CodePolicy(denied_modules=[])
        result = policy.evaluate(code="m = __import__('os')")
        assert result.allowed is False
        assert any("__import__" in v for v in result.violations)

    def test_allow_dunder_import_when_disabled(self) -> None:
        policy = CodePolicy(denied_modules=[], deny_dynamic_import=False)
        result = policy.evaluate(code="m = __import__('os')")
        # Still blocked by denied_modules check if "os" is in the denied list,
        # but __import__ itself should not be flagged
        violations_about_import = [v for v in result.violations if "__import__" in v]
        assert len(violations_about_import) == 0


class TestCodePolicyMaxLines:
    def test_within_limit(self) -> None:
        policy = CodePolicy(denied_modules=[], max_code_lines=10)
        code = "\n".join(["x = 1"] * 5)
        result = policy.evaluate(code=code)
        assert result.allowed is True

    def test_exceeds_limit(self) -> None:
        policy = CodePolicy(denied_modules=[], max_code_lines=3)
        code = "\n".join(["x = 1"] * 10)
        result = policy.evaluate(code=code)
        assert result.allowed is False
        assert any("lines" in v for v in result.violations)


class TestCodePolicyNetwork:
    def test_deny_network_by_default(self) -> None:
        policy = CodePolicy(denied_modules=[])
        result = policy.evaluate(code="import socket")
        assert result.allowed is False

    def test_allow_network_when_enabled(self) -> None:
        policy = CodePolicy(denied_modules=[], allow_network=True)
        result = policy.evaluate(code="import socket")
        assert result.allowed is True


class TestCodePolicySyntaxError:
    def test_syntax_error_denied(self) -> None:
        policy = CodePolicy(denied_modules=[])
        result = policy.evaluate(code="def (broken")
        assert result.allowed is False
        assert any("syntax" in v.lower() for v in result.violations)


class TestCodePolicyPolicyName:
    def test_result_has_policy_name(self) -> None:
        policy = CodePolicy(denied_modules=[])
        result = policy.evaluate(code="x = 1")
        assert result.policy_name == "CodePolicy"
