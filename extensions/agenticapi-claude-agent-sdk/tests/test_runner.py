"""Tests for :class:`ClaudeAgentRunner`."""

from __future__ import annotations

from typing import Any

import pytest
from agenticapi.harness.audit.recorder import AuditRecorder
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.interface.intent import Intent, IntentAction
from agenticapi.runtime.context import AgentContext
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition
from agenticapi.runtime.tools.registry import ToolRegistry

from agenticapi_claude_agent_sdk.exceptions import ClaudeAgentSDKRunError
from agenticapi_claude_agent_sdk.runner import ClaudeAgentRunner


def _intent(text: str = "do the thing") -> Intent:
    return Intent(raw=text, action=IntentAction.READ, domain="general")


def _context() -> AgentContext:
    return AgentContext(trace_id="trace-1", endpoint_name="ep")


class _NoopTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="db",
            description="Stub DB",
            capabilities=[ToolCapability.READ],
        )

    async def invoke(self, **kwargs: Any) -> Any:
        del kwargs
        return [{"id": 1}]


async def test_run_returns_agent_response_for_text_session(stub_messages: Any) -> None:
    from tests.conftest import StubAssistantMessage, StubResultMessage, StubTextBlock

    stub_messages(
        [
            StubAssistantMessage(content=[StubTextBlock(text="hi there")]),
            StubResultMessage(result="hi there", session_id="s1"),
        ]
    )

    runner = ClaudeAgentRunner(system_prompt="be brief")
    response = await runner.run(intent=_intent("ping"), context=_context())

    assert response.status == "completed"
    assert response.result == "hi there"
    assert response.confidence == 1.0


async def test_run_includes_context_window_in_prompt(stub_messages: Any, stub_state: Any) -> None:
    from tests.conftest import StubAssistantMessage, StubResultMessage, StubTextBlock

    stub_messages(
        [
            StubAssistantMessage(content=[StubTextBlock(text="ok")]),
            StubResultMessage(result="ok"),
        ]
    )

    ctx = _context()
    ctx.add_context("schema", "users(id, email)", source="db")
    runner = ClaudeAgentRunner()
    await runner.run(intent=_intent(), context=ctx)

    assert "<context>" in stub_state.last_query_prompt
    assert "users(id, email)" in stub_state.last_query_prompt


async def test_run_records_audit_trace_when_recorder_supplied(stub_messages: Any) -> None:
    from tests.conftest import StubAssistantMessage, StubResultMessage, StubTextBlock

    stub_messages(
        [
            StubAssistantMessage(content=[StubTextBlock(text="ok")]),
            StubResultMessage(result="ok"),
        ]
    )

    recorder = AuditRecorder()
    runner = ClaudeAgentRunner(audit_recorder=recorder)
    response = await runner.run(intent=_intent(), context=_context())

    records = recorder.get_records()
    assert len(records) == 1
    assert records[0].endpoint_name == "ep"
    assert response.execution_trace_id == records[0].trace_id


async def test_run_raises_on_sdk_error(stub_messages: Any) -> None:
    from tests.conftest import StubResultMessage

    stub_messages(
        [
            StubResultMessage(is_error=True, errors=["server"], subtype="error_during_execution"),
        ]
    )

    runner = ClaudeAgentRunner()
    with pytest.raises(ClaudeAgentSDKRunError):
        await runner.run(intent=_intent(), context=_context())


async def test_run_builds_mcp_server_from_registry(stub_messages: Any, stub_state: Any) -> None:
    from tests.conftest import StubAssistantMessage, StubResultMessage, StubTextBlock

    stub_messages(
        [
            StubAssistantMessage(content=[StubTextBlock(text="ok")]),
            StubResultMessage(result="ok"),
        ]
    )

    registry = ToolRegistry()
    registry.register(_NoopTool())

    runner = ClaudeAgentRunner(tool_registry=registry, mcp_server_name="agenticapi")
    await runner.run(intent=_intent(), context=_context())

    options = stub_state.last_query_options
    assert "agenticapi" in options.mcp_servers
    assert "mcp__agenticapi__db" in options.allowed_tools
    # The hook is registered for PreToolUse
    assert "PreToolUse" in (options.hooks or {})


async def test_run_with_policies_attaches_can_use_tool(stub_messages: Any, stub_state: Any) -> None:
    from tests.conftest import StubAssistantMessage, StubResultMessage, StubTextBlock

    stub_messages(
        [
            StubAssistantMessage(content=[StubTextBlock(text="ok")]),
            StubResultMessage(result="ok"),
        ]
    )

    runner = ClaudeAgentRunner(policies=[CodePolicy(denied_modules=["os"])])
    await runner.run(intent=_intent(), context=_context())

    options = stub_state.last_query_options
    assert callable(options.can_use_tool)


async def test_stream_yields_session_events(stub_messages: Any) -> None:
    from tests.conftest import (
        StubAssistantMessage,
        StubResultMessage,
        StubTextBlock,
    )

    stub_messages(
        [
            StubAssistantMessage(content=[StubTextBlock(text="hello")]),
            StubResultMessage(result="hello"),
        ]
    )

    runner = ClaudeAgentRunner()
    kinds: list[str] = []
    async for event in runner.stream(intent=_intent(), context=_context()):
        kinds.append(event.kind)

    assert kinds == ["text", "result"]
