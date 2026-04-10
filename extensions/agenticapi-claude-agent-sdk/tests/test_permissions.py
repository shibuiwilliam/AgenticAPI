"""Tests for the harness ↔ SDK permission adapter."""

from __future__ import annotations

from agenticapi.harness.policy.code_policy import CodePolicy

from agenticapi_claude_agent_sdk.permissions import HarnessPermissionAdapter


async def test_can_use_tool_allows_unknown_tool_when_not_strict() -> None:
    adapter = HarnessPermissionAdapter()
    result = await adapter.can_use_tool("Read", {"file_path": "x"}, context=None)
    assert result.behavior == "allow"
    assert adapter.decisions[-1].allowed is True


async def test_can_use_tool_denies_when_in_deny_list() -> None:
    adapter = HarnessPermissionAdapter(denied_tool_names=["Bash"])
    result = await adapter.can_use_tool("Bash", {"command": "ls"}, context=None)
    assert result.behavior == "deny"
    assert "deny list" in result.message
    assert adapter.decisions[-1].allowed is False


async def test_can_use_tool_strict_mode_denies_unknown() -> None:
    adapter = HarnessPermissionAdapter(
        allowed_tool_names=["Read"],
        deny_unknown_tools=True,
    )
    deny = await adapter.can_use_tool("Bash", {"command": "ls"}, context=None)
    allow = await adapter.can_use_tool("Read", {"file_path": "x"}, context=None)
    assert deny.behavior == "deny"
    assert allow.behavior == "allow"


async def test_can_use_tool_does_not_run_python_policy_on_bash() -> None:
    """Bash payloads must not be parsed as Python — guarded by the hook instead."""
    policy = CodePolicy(denied_modules=["os"])
    adapter = HarnessPermissionAdapter(policies=[policy])
    result = await adapter.can_use_tool(
        "Bash",
        {"command": "ls -la /tmp"},
        context=None,
    )
    assert result.behavior == "allow"


async def test_can_use_tool_enforces_code_policy_on_write() -> None:
    policy = CodePolicy(denied_modules=["os"])
    adapter = HarnessPermissionAdapter(policies=[policy])
    result = await adapter.can_use_tool(
        "Write",
        {"file_path": "evil.py", "content": "import os\nos.system('rm -rf /')"},
        context=None,
    )
    assert result.behavior == "deny"
    assert "Policy violation" in result.message
    assert any(not d.allowed for d in adapter.decisions)


async def test_pre_tool_use_hook_blocks_dangerous_python_write() -> None:
    adapter = HarnessPermissionAdapter()
    output = await adapter.pre_tool_use_hook(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "danger.py", "content": "eval('1+1')"},
        },
        tool_use_id=None,
        context=None,
    )
    assert "hookSpecificOutput" in output
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


async def test_pre_tool_use_hook_blocks_rm_rf_root() -> None:
    adapter = HarnessPermissionAdapter()
    output = await adapter.pre_tool_use_hook(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /usr/local"}},
        tool_use_id=None,
        context=None,
    )
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


async def test_pre_tool_use_hook_passes_safe_input() -> None:
    adapter = HarnessPermissionAdapter()
    output = await adapter.pre_tool_use_hook(
        {"tool_name": "Bash", "tool_input": {"command": "echo hello"}},
        tool_use_id=None,
        context=None,
    )
    assert output == {}


async def test_pre_tool_use_hook_ignores_non_code_tools() -> None:
    adapter = HarnessPermissionAdapter()
    output = await adapter.pre_tool_use_hook(
        {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
        tool_use_id=None,
        context=None,
    )
    assert output == {}


def test_decisions_can_be_reset() -> None:
    adapter = HarnessPermissionAdapter()
    adapter._decisions.append(type("D", (), {"tool_name": "x", "allowed": True, "reason": "", "violations": []})())
    adapter.reset()
    assert adapter.decisions == []
