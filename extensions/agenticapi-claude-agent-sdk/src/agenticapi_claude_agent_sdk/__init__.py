"""Claude Agent SDK extension for AgenticAPI.

This package wraps the `claude-agent-sdk
<https://code.claude.com/docs/en/agent-sdk/overview>`_ so it can be
used as a first-class execution strategy inside an
:class:`agenticapi.AgenticApp`.

Two integration shapes are provided:

1. :class:`ClaudeAgentRunner` — the recommended high-level entry
   point. Runs the SDK's full agentic loop (planning, tool use,
   reflection) inside an AgenticAPI endpoint, bridges AgenticAPI
   policies into the SDK's permission system, exposes AgenticAPI
   tools to the model via an in-process MCP server, and emits an
   :class:`agenticapi.AgentResponse` with optional audit trace.

2. :class:`ClaudeAgentSDKBackend` — a thin
   :class:`agenticapi.runtime.llm.base.LLMBackend` adapter for
   one-shot text completions, suitable for AgenticAPI's intent
   parser and code generator.

The package is importable even when ``claude_agent_sdk`` is not
installed; the SDK is loaded lazily on first call to :meth:`run`,
:meth:`generate`, or :func:`build_sdk_mcp_server_from_registry`. If
the SDK is missing at that point, a friendly
:class:`ClaudeAgentSDKNotInstalledError` is raised instead of an
opaque ``ImportError``.
"""

from __future__ import annotations

from agenticapi_claude_agent_sdk.backend import ClaudeAgentSDKBackend
from agenticapi_claude_agent_sdk.exceptions import (
    ClaudeAgentSDKError,
    ClaudeAgentSDKNotInstalledError,
    ClaudeAgentSDKRunError,
)
from agenticapi_claude_agent_sdk.messages import (
    AgentSessionEvent,
    AgentSessionResult,
    ToolCallRecord,
    collect_session,
    stream_session_events,
)
from agenticapi_claude_agent_sdk.options import build_claude_agent_options
from agenticapi_claude_agent_sdk.permissions import (
    HarnessPermissionAdapter,
    PermissionDecision,
)
from agenticapi_claude_agent_sdk.runner import ClaudeAgentRunner
from agenticapi_claude_agent_sdk.tools import (
    build_sdk_mcp_server_from_registry,
    sdk_tool_from_agenticapi_tool,
)

__version__ = "0.1.0"

__all__ = [
    "AgentSessionEvent",
    "AgentSessionResult",
    "ClaudeAgentRunner",
    "ClaudeAgentSDKBackend",
    "ClaudeAgentSDKError",
    "ClaudeAgentSDKNotInstalledError",
    "ClaudeAgentSDKRunError",
    "HarnessPermissionAdapter",
    "PermissionDecision",
    "ToolCallRecord",
    "__version__",
    "build_claude_agent_options",
    "build_sdk_mcp_server_from_registry",
    "collect_session",
    "sdk_tool_from_agenticapi_tool",
    "stream_session_events",
]
