"""Tests for the lazy import shim."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

from agenticapi.ext.claude_agent_sdk import _imports
from agenticapi.ext.claude_agent_sdk.exceptions import ClaudeAgentSDKNotInstalledError


def test_load_sdk_returns_cached_module() -> None:
    first = _imports.load_sdk()
    second = _imports.load_sdk()
    assert first is second


def test_get_attr_resolves_known_symbol() -> None:
    options = _imports.get_attr("ClaudeAgentOptions")
    assert options is not None


def test_friendly_error_when_sdk_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removing the stub from sys.modules should produce a friendly error."""
    saved = sys.modules.pop("claude_agent_sdk", None)
    try:
        _imports._reset_cache_for_tests()
        # Patch importlib so re-import fails.
        import importlib

        original_import = importlib.import_module

        def _fail(name: str) -> ModuleType:
            if name == "claude_agent_sdk":
                raise ImportError("not installed")
            return original_import(name)

        monkeypatch.setattr(importlib, "import_module", _fail)
        with pytest.raises(ClaudeAgentSDKNotInstalledError):
            _imports.load_sdk()
    finally:
        if saved is not None:
            sys.modules["claude_agent_sdk"] = saved
        _imports._reset_cache_for_tests()
