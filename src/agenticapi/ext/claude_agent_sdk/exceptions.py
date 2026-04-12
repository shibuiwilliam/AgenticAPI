"""Exception hierarchy for the Claude Agent SDK extension.

All extension errors inherit from :class:`ClaudeAgentSDKError`, which itself
inherits from :class:`agenticapi.AgenticAPIError`. This makes them
catchable in the same ``except`` clause as native AgenticAPI errors and
ensures they map cleanly to HTTP status codes via
``agenticapi.exceptions.EXCEPTION_STATUS_MAP``.
"""

from __future__ import annotations

from agenticapi.exceptions import AgentRuntimeError


class ClaudeAgentSDKError(AgentRuntimeError):
    """Base error for the Claude Agent SDK extension."""


class ClaudeAgentSDKNotInstalledError(ClaudeAgentSDKError):
    """Raised when ``claude_agent_sdk`` is not importable.

    The extension's classes can be imported even when the SDK isn't
    installed, but actually invoking them raises this error so users
    get a clear, actionable message instead of an opaque ImportError
    deep inside an event loop.
    """

    def __init__(self, original_error: BaseException | None = None) -> None:
        message = (
            "claude-agent-sdk is not installed. Install it with:\n"
            "    pip install claude-agent-sdk\n"
            "or install this extension with the SDK pulled in automatically:\n"
            "    pip install agentharnessapi-claude-agent-sdk"
        )
        super().__init__(message)
        self.__cause__ = original_error


class ClaudeAgentSDKRunError(ClaudeAgentSDKError):
    """Raised when a Claude Agent SDK session ends with an error.

    Wraps the SDK's own ``ResultMessage.is_error == True`` and
    transport-level errors so callers always see a typed exception.
    """

    def __init__(
        self,
        message: str,
        *,
        subtype: str | None = None,
        session_id: str | None = None,
        errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.subtype = subtype
        self.session_id = session_id
        self.errors = errors or []
