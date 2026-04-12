"""Unit tests for ``agenticapi init`` CLI command (INIT-1)."""

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003

import pytest

from agenticapi.cli.init import run_init


class TestRunInit:
    def test_creates_project_directory(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        result = run_init("my_agent")
        assert result == tmp_path / "my_agent"
        assert result.is_dir()

    def test_creates_expected_files(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        run_init("test_project")
        project = tmp_path / "test_project"

        expected_files = [
            "app.py",
            "tools.py",
            "evals/golden.yaml",
            ".env.example",
            "pyproject.toml",
            "README.md",
        ]
        for f in expected_files:
            assert (project / f).exists(), f"Missing {f}"

    def test_app_py_contains_project_name(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        run_init("my_cool_agent")
        content = (tmp_path / "my_cool_agent" / "app.py").read_text()
        assert "my_cool_agent" in content

    def test_pyproject_contains_dependency(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        run_init("demo")
        content = (tmp_path / "demo" / "pyproject.toml").read_text()
        assert "agenticapi>=0.1.0" in content

    def test_golden_yaml_has_cases(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        run_init("demo")
        content = (tmp_path / "demo" / "evals" / "golden.yaml").read_text()
        assert "cases:" in content
        assert "endpoint: ask" in content

    def test_raises_if_directory_exists(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        (tmp_path / "existing").mkdir()
        with pytest.raises(SystemExit):
            run_init("existing")

    def test_generated_app_imports_cleanly(self, tmp_path: Path) -> None:
        """The generated app.py should be valid Python (syntax check)."""
        os.chdir(tmp_path)
        run_init("importtest")
        app_py = (tmp_path / "importtest" / "app.py").read_text()
        # Compile to check syntax — doesn't execute imports.
        compile(app_py, "app.py", "exec")

    def test_generated_tools_imports_cleanly(self, tmp_path: Path) -> None:
        os.chdir(tmp_path)
        run_init("importtest2")
        tools_py = (tmp_path / "importtest2" / "tools.py").read_text()
        compile(tools_py, "tools.py", "exec")
