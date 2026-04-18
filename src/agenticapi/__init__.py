"""AgenticAPI — Agent-native web framework with harness engineering."""

from __future__ import annotations

from agenticapi._compat import MIN_PYTHON_VERSION as _MIN_PY  # noqa: F401 (side-effect: version check)
from agenticapi.app import AgenticApp
from agenticapi.dependencies import Dependency, Depends
from agenticapi.exceptions import (
    AgenticAPIError,
    ApprovalDenied,
    ApprovalRequired,
    ApprovalTimeout,
    AuthenticationError,
    AuthorizationError,
    BudgetExceeded,
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
    AutonomyPolicy,
    AutonomySignal,
    BudgetPolicy,
    CodePolicy,
    DataPolicy,
    EscalateWhen,
    HarnessEngine,
    PIIHit,
    PIIPolicy,
    PricingRegistry,
    PromptInjectionPolicy,
    ResourcePolicy,
    RuntimePolicy,
    redact_pii,
)
from agenticapi.interface import (
    AgentEvent,
    AgentResponse,
    AgentStream,
    AgentTasks,
    FileResult,
    HTMLResult,
    HtmxHeaders,
    Intent,
    IntentAction,
    IntentParser,
    IntentScope,
    PlainTextResult,
    UploadedFiles,
    UploadFile,
)
from agenticapi.interface.htmx import htmx_response_headers
from agenticapi.mesh import AgentMesh, MeshContext
from agenticapi.routing import AgentRouter
from agenticapi.runtime.code_cache import CachedCode, CodeCache, InMemoryCodeCache
from agenticapi.runtime.context import AgentContext
from agenticapi.runtime.loop import LoopConfig, LoopResult, ToolCallRecord, run_agentic_loop
from agenticapi.runtime.memory import (
    InMemoryMemoryStore,
    MemoryKind,
    MemoryRecord,
    MemoryStore,
    SqliteMemoryStore,
)
from agenticapi.runtime.tools import tool
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
from agenticapi.workflow import (
    AgentWorkflow,
    InMemoryWorkflowStore,
    SqliteWorkflowStore,
    StepConfig,
    WorkflowContext,
    WorkflowResult,
    WorkflowState,
    WorkflowStore,
)

try:
    from agenticapi._version import __version__
except ModuleNotFoundError:  # editable install without build
    __version__ = "0.0.0.dev0"

# Optional: HarnessMCPServer requires ``pip install agentharnessapi[mcp]``.
import contextlib

with contextlib.suppress(ImportError):
    from agenticapi.mcp_tools import HarnessMCPServer

__all__ = [
    "APIKeyHeader",
    "APIKeyQuery",
    "AgentContext",
    "AgentEvent",
    "AgentMesh",
    "AgentResponse",
    "AgentRouter",
    "AgentStream",
    "AgentTasks",
    "AgentWorkflow",
    "AgenticAPIError",
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
    "AutonomyLevel",
    "AutonomyPolicy",
    "AutonomySignal",
    "BudgetExceeded",
    "BudgetPolicy",
    "CachedCode",
    "CodeCache",
    "CodeExecutionError",
    "CodeGenerationError",
    "CodePolicy",
    "DataPolicy",
    "Dependency",
    "Depends",
    "EscalateWhen",
    "FileResult",
    "HTMLResult",
    "HTTPBasic",
    "HTTPBearer",
    "HarnessEngine",
    "HarnessError",
    "HarnessMCPServer",
    "HtmxHeaders",
    "InMemoryCodeCache",
    "InMemoryMemoryStore",
    "InMemoryWorkflowStore",
    "Intent",
    "IntentAction",
    "IntentParseError",
    "IntentParser",
    "IntentScope",
    "LoopConfig",
    "LoopResult",
    "MemoryKind",
    "MemoryRecord",
    "MemoryStore",
    "MeshContext",
    "PIIHit",
    "PIIPolicy",
    "PlainTextResult",
    "PolicyViolation",
    "PricingRegistry",
    "PromptInjectionPolicy",
    "ResourcePolicy",
    "RuntimePolicy",
    "SandboxViolation",
    "SessionError",
    "Severity",
    "SqliteMemoryStore",
    "SqliteWorkflowStore",
    "StepConfig",
    "ToolCallRecord",
    "ToolError",
    "TraceLevel",
    "UploadFile",
    "UploadedFiles",
    "WorkflowContext",
    "WorkflowResult",
    "WorkflowState",
    "WorkflowStore",
    "__version__",
    "htmx_response_headers",
    "redact_pii",
    "run_agentic_loop",
    "tool",
]
