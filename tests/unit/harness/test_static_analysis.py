"""Tests for check_code_safety static analysis."""

from __future__ import annotations

from agenticapi.harness.sandbox.static_analysis import check_code_safety


class TestSafeCode:
    def test_simple_assignment(self) -> None:
        result = check_code_safety("x = 1 + 2")
        assert result.safe is True
        assert result.violations == []

    def test_function_definition(self) -> None:
        code = "def add(a, b):\n    return a + b"
        result = check_code_safety(code)
        assert result.safe is True

    def test_list_comprehension(self) -> None:
        code = "squares = [x**2 for x in range(10)]"
        result = check_code_safety(code)
        assert result.safe is True


class TestDeniedImports:
    def test_denied_import(self) -> None:
        result = check_code_safety("import os", denied_modules=["os"])
        assert result.safe is False
        assert any(v.rule == "denied_import" for v in result.violations)

    def test_denied_from_import(self) -> None:
        result = check_code_safety("from os.path import join", denied_modules=["os"])
        assert result.safe is False

    def test_denied_import_not_in_list(self) -> None:
        result = check_code_safety("import json", denied_modules=["os"])
        assert result.safe is True

    def test_allowed_modules_whitelist(self) -> None:
        result = check_code_safety("import os", allowed_modules=["json", "math"])
        assert result.safe is False
        assert any(v.rule == "unlisted_import" for v in result.violations)

    def test_allowed_modules_whitelist_pass(self) -> None:
        result = check_code_safety("import json", allowed_modules=["json", "math"])
        assert result.safe is True


class TestEvalExec:
    def test_eval_detected(self) -> None:
        result = check_code_safety("x = eval('1+1')")
        assert result.safe is False
        assert any(v.rule == "eval_exec" for v in result.violations)

    def test_exec_detected(self) -> None:
        result = check_code_safety("exec('print(1)')")
        assert result.safe is False
        assert any(v.rule == "eval_exec" for v in result.violations)

    def test_eval_allowed_when_disabled(self) -> None:
        result = check_code_safety("x = eval('1+1')", deny_eval_exec=False)
        eval_violations = [v for v in result.violations if v.rule == "eval_exec"]
        assert len(eval_violations) == 0


class TestDynamicImport:
    def test_dunder_import_detected(self) -> None:
        result = check_code_safety("m = __import__('os')")
        assert result.safe is False
        assert any(v.rule == "dynamic_import" for v in result.violations)

    def test_dunder_import_allowed_when_disabled(self) -> None:
        result = check_code_safety("m = __import__('os')", deny_dynamic_import=False)
        import_violations = [v for v in result.violations if v.rule == "dynamic_import"]
        assert len(import_violations) == 0


class TestFileIO:
    def test_open_detected(self) -> None:
        result = check_code_safety("f = open('file.txt')")
        assert result.safe is False
        assert any(v.rule == "file_io" for v in result.violations)


class TestDangerousBuiltins:
    def test_compile_detected(self) -> None:
        result = check_code_safety("c = compile('x=1', '<string>', 'exec')")
        # compile is a warning, not an error
        assert any(v.rule == "dangerous_builtin" for v in result.violations)

    def test_globals_detected(self) -> None:
        result = check_code_safety("g = globals()")
        assert any(v.rule == "dangerous_builtin" for v in result.violations)

    def test_locals_detected(self) -> None:
        result = check_code_safety("l = locals()")
        assert any(v.rule == "dangerous_builtin" for v in result.violations)

    def test_vars_detected(self) -> None:
        result = check_code_safety("v = vars()")
        assert any(v.rule == "dangerous_builtin" for v in result.violations)

    def test_breakpoint_detected(self) -> None:
        result = check_code_safety("breakpoint()")
        assert any(v.rule == "dangerous_builtin" for v in result.violations)


class TestSyntaxError:
    def test_syntax_error_reported(self) -> None:
        result = check_code_safety("def (broken")
        assert result.safe is False
        assert any(v.rule == "syntax_error" for v in result.violations)


class TestViolationMetadata:
    def test_has_line_and_col(self) -> None:
        result = check_code_safety("import os", denied_modules=["os"])
        assert result.safe is False
        violation = result.violations[0]
        assert violation.line >= 1
        assert violation.severity == "error"

    def test_multiple_violations(self) -> None:
        code = "import os\nx = eval('1')"
        result = check_code_safety(code, denied_modules=["os"])
        assert result.safe is False
        assert len(result.violations) >= 2


class TestMultiLineImports:
    def test_multiline_from_import(self) -> None:
        code = "from os import (\n    system,\n    path\n)"
        result = check_code_safety(code, denied_modules=["os"])
        assert result.safe is False
        assert any("os" in v.description for v in result.violations)

    def test_submodule_import(self) -> None:
        code = "import os.path"
        result = check_code_safety(code, denied_modules=["os"])
        assert result.safe is False

    def test_from_submodule_import(self) -> None:
        code = "from os.path import join"
        result = check_code_safety(code, denied_modules=["os"])
        assert result.safe is False


class TestAttributeAccessBypass:
    def test_getattr_detected(self) -> None:
        code = "x = getattr(module, 'system')"
        result = check_code_safety(code)
        assert any(v.rule == "dangerous_builtin" for v in result.violations)

    def test_setattr_detected(self) -> None:
        code = "setattr(obj, 'value', 42)"
        result = check_code_safety(code)
        assert any(v.rule == "dangerous_builtin" for v in result.violations)

    def test_delattr_detected(self) -> None:
        code = "delattr(obj, 'attr')"
        result = check_code_safety(code)
        assert any(v.rule == "dangerous_builtin" for v in result.violations)

    def test_help_detected(self) -> None:
        code = "help(something)"
        result = check_code_safety(code)
        assert any(v.rule == "dangerous_builtin" for v in result.violations)
