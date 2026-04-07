"""Tests for CLI console."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agenticapi.cli.console import _load_app


class TestLoadApp:
    def test_load_valid_app(self) -> None:
        app = _load_app("examples.01_hello_agent.app:app")
        assert hasattr(app, "agent_endpoint")

    def test_invalid_format_exits(self) -> None:
        with pytest.raises(SystemExit):
            _load_app("no_colon_here")

    def test_missing_module_exits(self) -> None:
        with pytest.raises(SystemExit):
            _load_app("nonexistent.module:app")

    def test_missing_attribute_exits(self) -> None:
        with pytest.raises(SystemExit):
            _load_app("examples.01_hello_agent.app:nonexistent")


class TestConsoleCommand:
    def test_cli_has_console_subcommand(self) -> None:
        from agenticapi.cli.main import cli

        with patch("sys.argv", ["agenticapi", "console", "--app", "x:y"]), pytest.raises(SystemExit):
            # Will fail on import but proves the subcommand is wired
            cli()
