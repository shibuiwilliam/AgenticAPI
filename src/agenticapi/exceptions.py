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


class BudgetExceeded(PolicyViolation):
    """Cost or token budget exceeded for this request, session, or user.

    Subclass of :class:`PolicyViolation` so it maps to the same HTTP 403
    status as other policy denials and so existing handlers that catch
    ``PolicyViolation`` continue to work.

    Attributes:
        scope: One of ``"request"``, ``"session"``, ``"user"``,
            ``"endpoint"`` describing which budget tier was breached.
        limit_usd: The configured ceiling that was hit.
        observed_usd: The cost (or estimate) that triggered the breach.
        model: The model identifier in play, if known.
    """

    def __init__(
        self,
        *,
        scope: str,
        limit_usd: float,
        observed_usd: float,
        model: str | None = None,
        violation: str | None = None,
    ) -> None:
        self.scope = scope
        self.limit_usd = limit_usd
        self.observed_usd = observed_usd
        self.model = model
        message = violation or (
            f"Budget exceeded for scope={scope}: observed ${observed_usd:.4f} > limit ${limit_usd:.4f}"
        )
        super().__init__(policy="BudgetPolicy", violation=message)


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
    BudgetExceeded: 402,  # Payment Required — semantic match for cost limits
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
