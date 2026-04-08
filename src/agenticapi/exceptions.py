"""Exception hierarchy for AgenticAPI.

All exceptions inherit from AgenticAPIError. The hierarchy is organized
by layer: Harness, Runtime, and Interface.
"""

from __future__ import annotations


class AgenticAPIError(Exception):
    """Base exception for all AgenticAPI errors."""


# --- Harness layer ---


class HarnessError(AgenticAPIError):
    """Base exception for harness engine errors."""


class PolicyViolation(HarnessError):
    """Policy violation. Generated code does not conform to policy."""

    def __init__(
        self,
        policy: str,
        violation: str,
        generated_code: str | None = None,
    ) -> None:
        self.policy = policy
        self.violation = violation
        self.generated_code = generated_code
        super().__init__(f"Policy '{policy}' violated: {violation}")


class SandboxViolation(HarnessError):
    """Sandbox violation. Forbidden operation detected at runtime."""


class ApprovalRequired(HarnessError):
    """Approval required. Human approval is needed to continue."""

    def __init__(
        self,
        message: str = "Approval required",
        *,
        request_id: str | None = None,
        approvers: list[str] | None = None,
    ) -> None:
        self.request_id = request_id
        self.approvers = approvers or []
        super().__init__(message)


class ApprovalDenied(HarnessError):
    """Approval was denied."""


class ApprovalTimeout(HarnessError):
    """Approval timed out."""


# --- Runtime layer ---


class AgentRuntimeError(AgenticAPIError):
    """Base exception for agent runtime errors."""


class CodeGenerationError(AgentRuntimeError):
    """Code generation failed."""


class CodeExecutionError(AgentRuntimeError):
    """Generated code execution failed."""


class ToolError(AgentRuntimeError):
    """Tool invocation failed."""


class ContextError(AgentRuntimeError):
    """Context construction failed."""


# --- Interface layer ---


class InterfaceError(AgenticAPIError):
    """Base exception for interface layer errors."""


class IntentParseError(InterfaceError):
    """Intent parsing failed."""


class SessionError(InterfaceError):
    """Session management error."""


class A2AError(InterfaceError):
    """Agent-to-Agent communication error."""


class AuthenticationError(InterfaceError):
    """Authentication failed or credentials missing."""


class AuthorizationError(InterfaceError):
    """Authenticated user lacks required permissions."""


# --- HTTP status code mapping ---

EXCEPTION_STATUS_MAP: dict[type[AgenticAPIError], int] = {
    IntentParseError: 400,
    PolicyViolation: 403,
    ApprovalRequired: 202,
    ApprovalDenied: 403,
    ApprovalTimeout: 408,
    SandboxViolation: 403,
    CodeGenerationError: 500,
    CodeExecutionError: 500,
    ToolError: 502,
    SessionError: 400,
    A2AError: 502,
    AuthenticationError: 401,
    AuthorizationError: 403,
}
