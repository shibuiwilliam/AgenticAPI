"""AgenticAPI — Agent-native web framework with harness engineering."""

from __future__ import annotations

from agenticapi._compat import MIN_PYTHON_VERSION as _MIN_PY  # noqa: F401 (side-effect: version check)
from agenticapi.app import AgenticApp
from agenticapi.exceptions import (
    AgenticAPIError,
    ApprovalDenied,
    ApprovalRequired,
    ApprovalTimeout,
    AuthenticationError,
    AuthorizationError,
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
    AgentTasks,
    FileResult,
    Intent,
    IntentAction,
    IntentParser,
    IntentScope,
    UploadedFiles,
    UploadFile,
)
from agenticapi.routing import AgentRouter
from agenticapi.runtime.context import AgentContext
from agenticapi.security import (
    APIKeyHeader,
    APIKeyQuery,
    AuthCredentials,
    Authenticator,
    AuthUser,
    HTTPBasic,
    HTTPBearer,
)
from agenticapi.types import AutonomyLevel, Severity, TraceLevel

__version__ = "0.1.0"

__all__ = [
    # Security
    "APIKeyHeader",
    "APIKeyQuery",
    # Runtime
    "AgentContext",
    # Interface
    "AgentResponse",
    "AgentRouter",
    "AgentTasks",
    # Exceptions
    "AgenticAPIError",
    # Core app
    "AgenticApp",
    "ApprovalDenied",
    "ApprovalRequired",
    "ApprovalRule",
    "ApprovalTimeout",
    "ApprovalWorkflow",
    "AuthCredentials",
    "AuthUser",
    "AuthenticationError",
    "Authenticator",
    "AuthorizationError",
    # Types
    "AutonomyLevel",
    "CodeExecutionError",
    "CodeGenerationError",
    # Harness
    "CodePolicy",
    "DataPolicy",
    # File handling
    "FileResult",
    # Security (contd)
    "HTTPBasic",
    "HTTPBearer",
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
    # File upload
    "UploadFile",
    "UploadedFiles",
    # Version
    "__version__",
]
