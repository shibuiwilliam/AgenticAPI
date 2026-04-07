"""Harness layer for AgenticAPI.

The harness layer controls agent behavior through policy evaluation,
static analysis, sandboxed execution, and audit recording. All agent
operations pass through the HarnessEngine.

Re-exports key types for convenient access.
"""

from __future__ import annotations

from agenticapi.harness.approval import (
    ApprovalNotifier,
    ApprovalRequest,
    ApprovalRule,
    ApprovalState,
    ApprovalWorkflow,
    LogNotifier,
)
from agenticapi.harness.audit import AuditRecorder, ExecutionTrace
from agenticapi.harness.engine import ExecutionResult, HarnessEngine
from agenticapi.harness.policy import (
    CodePolicy,
    DataPolicy,
    EvaluationResult,
    Policy,
    PolicyEvaluator,
    PolicyResult,
    ResourcePolicy,
    RuntimePolicy,
)
from agenticapi.harness.sandbox import (
    ProcessSandbox,
    ResourceLimits,
    SafetyResult,
    SandboxResult,
    SandboxRuntime,
    check_code_safety,
)

__all__ = [
    "ApprovalNotifier",
    "ApprovalRequest",
    "ApprovalRule",
    "ApprovalState",
    "ApprovalWorkflow",
    "AuditRecorder",
    "CodePolicy",
    "DataPolicy",
    "EvaluationResult",
    "ExecutionResult",
    "ExecutionTrace",
    "HarnessEngine",
    "LogNotifier",
    "Policy",
    "PolicyEvaluator",
    "PolicyResult",
    "ProcessSandbox",
    "ResourceLimits",
    "ResourcePolicy",
    "RuntimePolicy",
    "SafetyResult",
    "SandboxResult",
    "SandboxRuntime",
    "check_code_safety",
]
