"""Tests for the SDK message-stream collector."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from agenticapi.ext.claude_agent_sdk.exceptions import ClaudeAgentSDKRunError
from agenticapi.ext.claude_agent_sdk.messages import (
    AgentSessionEvent,
    collect_session,
    stream_session_events,
)


async def _stream(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


async def test_collect_session_text_only() -> None:
    from tests.unit.ext.claude_agent_sdk.conftest import (
        StubAssistantMessage,
        StubResultMessage,
        StubSystemMessage,
        StubTextBlock,
    )

    messages = [
        StubSystemMessage(subtype="init", data={"session_id": "abc"}),
        StubAssistantMessage(content=[StubTextBlock(text="hello")]),
        StubResultMessage(result="hello", session_id="abc"),
    ]

    session = await collect_session(_stream(messages))

    assert session.text == "hello"
    assert session.result_text == "hello"
    assert session.session_id == "abc"
    assert session.is_error is False


async def test_collect_session_tool_calls() -> None:
    from tests.unit.ext.claude_agent_sdk.conftest import (
        StubAssistantMessage,
        StubResultMessage,
        StubToolResultBlock,
        StubToolUseBlock,
        StubUserMessage,
    )

    messages = [
        StubAssistantMessage(
            content=[
                StubToolUseBlock(id="t1", name="Read", input={"file_path": "x.py"}),
            ]
        ),
        StubUserMessage(
            content=[
                StubToolResultBlock(tool_use_id="t1", content="contents", is_error=False),
            ]
        ),
        StubResultMessage(result="done"),
    ]

    session = await collect_session(_stream(messages))

    assert len(session.tool_calls) == 1
    call = session.tool_calls[0]
    assert call.name == "Read"
    assert call.input == {"file_path": "x.py"}
    assert call.result == "contents"
    assert call.is_error is False


async def test_collect_session_raises_on_error() -> None:
    from tests.unit.ext.claude_agent_sdk.conftest import StubResultMessage

    messages = [StubResultMessage(is_error=True, errors=["boom"], subtype="error_during_execution")]

    with pytest.raises(ClaudeAgentSDKRunError) as exc_info:
        await collect_session(_stream(messages), raise_on_error=True)
    assert exc_info.value.subtype == "error_during_execution"
    assert exc_info.value.errors == ["boom"]


async def test_collect_session_skips_error_when_disabled() -> None:
    from tests.unit.ext.claude_agent_sdk.conftest import StubResultMessage

    messages = [StubResultMessage(is_error=True, errors=["boom"])]
    session = await collect_session(_stream(messages), raise_on_error=False)
    assert session.is_error is True


async def test_session_to_agent_response_uses_structured_output() -> None:
    from tests.unit.ext.claude_agent_sdk.conftest import StubResultMessage

    messages = [StubResultMessage(result="text", structured_output={"k": "v"})]
    session = await collect_session(_stream(messages))
    response = session.to_agent_response()
    assert response.result == {"k": "v"}
    assert response.status == "completed"


async def test_session_generated_code_collects_tool_inputs() -> None:
    from tests.unit.ext.claude_agent_sdk.conftest import StubAssistantMessage, StubResultMessage, StubToolUseBlock

    messages = [
        StubAssistantMessage(content=[StubToolUseBlock(id="t1", name="Bash", input={"command": "ls -la"})]),
        StubResultMessage(result="ok"),
    ]
    session = await collect_session(_stream(messages))
    response = session.to_agent_response()
    assert response.generated_code is not None
    assert "ls -la" in response.generated_code


async def test_stream_session_events_emits_in_order() -> None:
    from tests.unit.ext.claude_agent_sdk.conftest import (
        StubAssistantMessage,
        StubResultMessage,
        StubSystemMessage,
        StubTextBlock,
        StubToolUseBlock,
    )

    messages = [
        StubSystemMessage(subtype="init", data={"session_id": "s"}),
        StubAssistantMessage(
            content=[
                StubTextBlock(text="thinking..."),
                StubToolUseBlock(id="t1", name="Read", input={"file_path": "a"}),
            ]
        ),
        StubResultMessage(result="done"),
    ]

    events: list[AgentSessionEvent] = []
    async for event in stream_session_events(_stream(messages)):
        events.append(event)

    kinds = [e.kind for e in events]
    assert kinds == ["system", "text", "tool_use", "result"]
