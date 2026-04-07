"""AgenticAPI — Agent-native web framework with harness engineering."""

from __future__ import annotations

from agenticapi._compat import MIN_PYTHON_VERSION as _MIN_PY  # noqa: F401 (side-effect: version check)
from agenticapi.app import AgenticApp
from agenticapi.exceptions import (
    AgenticAPIError,
    ApprovalDenied,
    ApprovalRequired,
    ApprovalTimeout,
    CodeExecutionError,
    CodeGenerationError,
    HarnessError,
    IntentParseError,
    PolicyViolation,
    SandboxViolation,
    SessionError,
    ToolError,
)
from agenticapi.harness import (
    ApprovalRule,
    ApprovalWorkflow,
    CodePolicy,
    DataPolicy,
    HarnessEngine,
    ResourcePolicy,
    RuntimePolicy,
)
from agenticapi.interface import (
    AgentResponse,
    Intent,
    IntentAction,
    IntentParser,
    IntentScope,
)
from agenticapi.routing import AgentRouter
from agenticapi.runtime.context import AgentContext
from agenticapi.types import AutonomyLevel, Severity, TraceLevel

__version__ = "0.1.0"

__all__ = [
    # Runtime
    "AgentContext",
    # Interface
    "AgentResponse",
    "AgentRouter",
    # Exceptions
    "AgenticAPIError",
    # Core app
    "AgenticApp",
    "ApprovalDenied",
    "ApprovalRequired",
    "ApprovalRule",
    "ApprovalTimeout",
    "ApprovalWorkflow",
    # Types
    "AutonomyLevel",
    "CodeExecutionError",
    "CodeGenerationError",
    # Harness
    "CodePolicy",
    "DataPolicy",
    "HarnessEngine",
    "HarnessError",
    "Intent",
    "IntentAction",
    "IntentParseError",
    "IntentParser",
    "IntentScope",
    "PolicyViolation",
    "ResourcePolicy",
    "RuntimePolicy",
    "SandboxViolation",
    "SessionError",
    "Severity",
    "ToolError",
    "TraceLevel",
    # Version
    "__version__",
]
