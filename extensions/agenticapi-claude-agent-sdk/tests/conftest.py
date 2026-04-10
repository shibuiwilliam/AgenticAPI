"""Shared pytest fixtures and a stub ``claude_agent_sdk`` module.

Tests run **without** the real SDK installed. Instead, this conftest
installs a small stub module under ``sys.modules['claude_agent_sdk']``
that provides just enough surface for the extension to import and
exercise its code paths.

The stub also exposes a ``set_messages()`` helper so individual tests
can prescribe the message stream that ``query()`` will yield.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# ---------------------------------------------------------------------------
# Stub message and option dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StubTextBlock:
    text: str


@dataclass
class StubThinkingBlock:
    thinking: str
    signature: str = ""


@dataclass
class StubToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class StubToolResultBlock:
    tool_use_id: str
    content: Any = None
    is_error: bool | None = None


@dataclass
class StubAssistantMessage:
    content: list[Any]
    model: str = "stub-model"
    parent_tool_use_id: str | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    message_id: str | None = None
    stop_reason: str | None = None
    session_id: str | None = None
    uuid: str | None = None

    @classmethod
    def __class_getitem__(cls, item: Any) -> type:
        return cls


@dataclass
class StubUserMessage:
    content: list[Any]


@dataclass
class StubSystemMessage:
    subtype: str
    data: dict[str, Any]


@dataclass
class StubResultMessage:
    subtype: str = "success"
    duration_ms: int = 100
    duration_api_ms: int = 50
    is_error: bool = False
    num_turns: int = 1
    session_id: str = "stub-session"
    stop_reason: str | None = None
    total_cost_usd: float | None = 0.0
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    model_usage: dict[str, Any] | None = None
    permission_denials: list[Any] | None = None
    errors: list[str] | None = None
    uuid: str | None = None


# Renamed for use as the actual class names the adapter looks up
# (the adapter uses ``type(message).__name__``).
StubTextBlock.__name__ = "TextBlock"
StubThinkingBlock.__name__ = "ThinkingBlock"
StubToolUseBlock.__name__ = "ToolUseBlock"
StubToolResultBlock.__name__ = "ToolResultBlock"
StubAssistantMessage.__name__ = "AssistantMessage"
StubUserMessage.__name__ = "UserMessage"
StubSystemMessage.__name__ = "SystemMessage"
StubResultMessage.__name__ = "ResultMessage"


@dataclass
class StubPermissionResultAllow:
    behavior: str = "allow"
    updated_input: dict[str, Any] | None = None
    updated_permissions: list[Any] | None = None


@dataclass
class StubPermissionResultDeny:
    behavior: str = "deny"
    message: str = ""
    interrupt: bool = False


@dataclass
class StubHookMatcher:
    matcher: str | None = None
    hooks: list[Any] = field(default_factory=list)
    timeout: float | None = None


@dataclass
class StubClaudeAgentOptions:
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    permission_mode: str = "default"
    system_prompt: str | None = None
    model: str | None = None
    max_turns: int | None = None
    cwd: Any = None
    env: dict[str, str] = field(default_factory=dict)
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    can_use_tool: Any = None
    hooks: dict[str, Any] | None = None
    extra_args: dict[str, str | None] = field(default_factory=dict)


@dataclass
class StubSdkMcpTool:
    name: str
    description: str
    input_schema: Any
    handler: Any


@dataclass
class StubMcpSdkServerConfig:
    name: str
    version: str
    tools: list[StubSdkMcpTool]


# ---------------------------------------------------------------------------
# Mutable per-test state
# ---------------------------------------------------------------------------


class _StubState:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.last_query_prompt: str | None = None
        self.last_query_options: Any = None
        self.tools_registered: list[StubSdkMcpTool] = []

    def reset(self) -> None:
        self.messages = []
        self.last_query_prompt = None
        self.last_query_options = None
        self.tools_registered = []


_state = _StubState()


def set_messages(messages: list[Any]) -> None:
    """Configure the message stream the next ``query()`` call will return."""
    _state.messages = list(messages)


def get_state() -> _StubState:
    return _state


# ---------------------------------------------------------------------------
# Stub query() and tool() and create_sdk_mcp_server()
# ---------------------------------------------------------------------------


def stub_query(
    *,
    prompt: Any,
    options: Any = None,
    transport: Any = None,
) -> AsyncIterator[Any]:
    del transport
    _state.last_query_prompt = prompt
    _state.last_query_options = options

    async def _stream() -> AsyncIterator[Any]:
        for msg in _state.messages:
            yield msg

    return _stream()


def stub_tool(name: str, description: str, input_schema: Any) -> Any:
    def _decorator(handler: Any) -> StubSdkMcpTool:
        tool = StubSdkMcpTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )
        _state.tools_registered.append(tool)
        return tool

    return _decorator


def stub_create_sdk_mcp_server(
    name: str,
    version: str = "1.0.0",
    tools: list[StubSdkMcpTool] | None = None,
) -> StubMcpSdkServerConfig:
    return StubMcpSdkServerConfig(name=name, version=version, tools=list(tools or []))


# ---------------------------------------------------------------------------
# Install the stub module before any extension import
# ---------------------------------------------------------------------------


def _install_stub_module() -> ModuleType:
    module = ModuleType("claude_agent_sdk")
    module.query = stub_query  # type: ignore[attr-defined]
    module.tool = stub_tool  # type: ignore[attr-defined]
    module.create_sdk_mcp_server = stub_create_sdk_mcp_server  # type: ignore[attr-defined]
    module.ClaudeAgentOptions = StubClaudeAgentOptions  # type: ignore[attr-defined]
    module.PermissionResultAllow = StubPermissionResultAllow  # type: ignore[attr-defined]
    module.PermissionResultDeny = StubPermissionResultDeny  # type: ignore[attr-defined]
    module.HookMatcher = StubHookMatcher  # type: ignore[attr-defined]
    module.AssistantMessage = StubAssistantMessage  # type: ignore[attr-defined]
    module.UserMessage = StubUserMessage  # type: ignore[attr-defined]
    module.SystemMessage = StubSystemMessage  # type: ignore[attr-defined]
    module.ResultMessage = StubResultMessage  # type: ignore[attr-defined]
    module.TextBlock = StubTextBlock  # type: ignore[attr-defined]
    module.ThinkingBlock = StubThinkingBlock  # type: ignore[attr-defined]
    module.ToolUseBlock = StubToolUseBlock  # type: ignore[attr-defined]
    module.ToolResultBlock = StubToolResultBlock  # type: ignore[attr-defined]
    module._stub_state = SimpleNamespace(  # type: ignore[attr-defined]
        set_messages=set_messages,
        get_state=get_state,
    )
    sys.modules["claude_agent_sdk"] = module
    return module


_install_stub_module()


# Reset the lazy-import cache after the stub module is installed so the
# extension picks up the stub on first call.
from agenticapi_claude_agent_sdk import _imports as _ext_imports  # noqa: E402

_ext_imports._reset_cache_for_tests()


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_stub_state() -> None:
    _state.reset()
    _ext_imports._reset_cache_for_tests()


@pytest.fixture
def stub_messages() -> Any:
    """Return a callable that sets the message stream for ``query()``."""
    return set_messages


@pytest.fixture
def stub_state() -> _StubState:
    """Return the live stub state object so tests can inspect it."""
    return _state
