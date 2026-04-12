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
from agenticapi.harness.audit import (
    AuditRecorder,
    AuditRecorderProtocol,
    ExecutionTrace,
    InMemoryAuditRecorder,
    SqliteAuditRecorder,
)
from agenticapi.harness.engine import ExecutionResult, HarnessEngine
from agenticapi.harness.policy import (
    AutonomyPolicy,
    AutonomySignal,
    AutonomyState,
    BudgetEvaluationContext,
    BudgetPolicy,
    CodePolicy,
    CostEstimate,
    DataPolicy,
    EscalateWhen,
    EvaluationResult,
    InjectionHit,
    InMemorySpendStore,
    ModelPricing,
    PIIHit,
    PIIPolicy,
    Policy,
    PolicyEvaluator,
    PolicyResult,
    PricingRegistry,
    PromptInjectionPolicy,
    ResourcePolicy,
    RuntimePolicy,
    SpendStore,
    redact_pii,
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
    "AuditRecorderProtocol",
    "AutonomyPolicy",
    "AutonomySignal",
    "AutonomyState",
    "BudgetEvaluationContext",
    "BudgetPolicy",
    "CodePolicy",
    "CostEstimate",
    "DataPolicy",
    "EscalateWhen",
    "EvaluationResult",
    "ExecutionResult",
    "ExecutionTrace",
    "HarnessEngine",
    "InMemoryAuditRecorder",
    "InMemorySpendStore",
    "InjectionHit",
    "LogNotifier",
    "ModelPricing",
    "PIIHit",
    "PIIPolicy",
    "Policy",
    "PolicyEvaluator",
    "PolicyResult",
    "PricingRegistry",
    "ProcessSandbox",
    "PromptInjectionPolicy",
    "ResourceLimits",
    "ResourcePolicy",
    "RuntimePolicy",
    "SafetyResult",
    "SandboxResult",
    "SandboxRuntime",
    "SpendStore",
    "SqliteAuditRecorder",
    "check_code_safety",
    "redact_pii",
]
