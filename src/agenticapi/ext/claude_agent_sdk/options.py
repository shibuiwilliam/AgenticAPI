"""Helper for building :class:`ClaudeAgentOptions` from AgenticAPI inputs.

Centralising the options construction in one place makes it easy to
test (we just inspect the resulting kwargs dict) and to evolve as the
SDK grows new options.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi.ext.claude_agent_sdk._imports import load_sdk

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from agenticapi.ext.claude_agent_sdk.permissions import HarnessPermissionAdapter


def build_claude_agent_options(
    *,
    system_prompt: str | None,
    model: str | None,
    allowed_tools: Sequence[str],
    disallowed_tools: Sequence[str],
    permission_mode: str,
    max_turns: int | None,
    cwd: str | Path | None,
    env: Mapping[str, str] | None,
    mcp_servers: Mapping[str, Any] | None,
    permission_adapter: HarnessPermissionAdapter | None,
    extra_options: Mapping[str, Any] | None,
) -> Any:
    """Construct a :class:`ClaudeAgentOptions` instance.

    Returns:
        A ``ClaudeAgentOptions`` populated from the supplied arguments.
        Unknown ``extra_options`` keys are passed through verbatim,
        which lets callers set future SDK fields without waiting for
        an extension release.
    """
    sdk = load_sdk()

    kwargs: dict[str, Any] = {
        "allowed_tools": list(allowed_tools),
        "disallowed_tools": list(disallowed_tools),
        "permission_mode": permission_mode,
    }
    if system_prompt is not None:
        kwargs["system_prompt"] = system_prompt
    if model is not None:
        kwargs["model"] = model
    if max_turns is not None:
        kwargs["max_turns"] = max_turns
    if cwd is not None:
        kwargs["cwd"] = cwd
    if env is not None:
        kwargs["env"] = dict(env)
    if mcp_servers:
        kwargs["mcp_servers"] = dict(mcp_servers)
    if permission_adapter is not None:
        kwargs["can_use_tool"] = permission_adapter.can_use_tool
        kwargs["hooks"] = {
            "PreToolUse": [
                sdk.HookMatcher(hooks=[permission_adapter.pre_tool_use_hook]),
            ],
        }
    if extra_options:
        kwargs.update(dict(extra_options))

    return sdk.ClaudeAgentOptions(**kwargs)
