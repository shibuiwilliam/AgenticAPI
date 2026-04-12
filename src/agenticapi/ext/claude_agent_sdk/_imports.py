"""Lazy import shim for ``claude_agent_sdk``.

The extension is designed so that ``import agenticapi.ext.claude_agent_sdk``
always succeeds, even when the SDK is not installed. The SDK is loaded
on first use via :func:`load_sdk`, which raises a friendly
:class:`ClaudeAgentSDKNotInstalledError` if the import fails.

This indirection also gives tests a single place to monkey-patch the
SDK module: install a fake module under the name ``claude_agent_sdk``
in ``sys.modules`` (see ``tests/conftest.py``) and the extension will
pick it up.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from agenticapi.ext.claude_agent_sdk.exceptions import ClaudeAgentSDKNotInstalledError

if TYPE_CHECKING:
    from types import ModuleType

_cached_module: ModuleType | None = None


def load_sdk() -> ModuleType:
    """Import and return the ``claude_agent_sdk`` module.

    The result is cached after the first successful import. Tests can
    reset the cache by calling :func:`_reset_cache_for_tests`.

    Returns:
        The ``claude_agent_sdk`` module.

    Raises:
        ClaudeAgentSDKNotInstalledError: If the SDK is not installed.
    """
    global _cached_module
    if _cached_module is not None:
        return _cached_module

    try:
        _cached_module = importlib.import_module("claude_agent_sdk")
    except ImportError as exc:
        raise ClaudeAgentSDKNotInstalledError(exc) from exc
    return _cached_module


def get_attr(name: str) -> Any:
    """Resolve a top-level attribute on the SDK module.

    Args:
        name: Attribute name to fetch from ``claude_agent_sdk``.

    Returns:
        The attribute value.

    Raises:
        ClaudeAgentSDKNotInstalledError: If the SDK is not installed.
        AttributeError: If the attribute does not exist on the SDK module.
    """
    module = load_sdk()
    return getattr(module, name)


def _reset_cache_for_tests() -> None:
    """Reset the cached module reference. Test-only helper."""
    global _cached_module
    _cached_module = None
