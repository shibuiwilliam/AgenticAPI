"""Harness engine orchestrating policy evaluation, static analysis, sandbox execution, and audit.

The HarnessEngine is the central component of the harness layer. All agent
operations pass through it to ensure safety and traceability.

Flow:
    1. Policy evaluation (raise PolicyViolation if denied)
    2. Static analysis (raise PolicyViolation if unsafe)
    3. Sandbox execution
    4. Audit trace recording
    5. Return ExecutionResult
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import ApprovalRequired, PolicyViolation, SandboxViolation
from agenticapi.harness.audit.recorder import AuditRecorder
from agenticapi.harness.audit.trace import ExecutionTrace
from agenticapi.harness.policy.evaluator import PolicyEvaluator
from agenticapi.harness.sandbox.base import ResourceLimits, SandboxResult
from agenticapi.harness.sandbox.process import ProcessSandbox
from agenticapi.harness.sandbox.static_analysis import check_code_safety

if TYPE_CHECKING:
    from agenticapi.harness.approval.workflow import ApprovalWorkflow
    from agenticapi.harness.policy.base import Policy
    from agenticapi.harness.sandbox.monitors import ExecutionMonitor
    from agenticapi.harness.sandbox.validators import ResultValidator
    from agenticapi.runtime.context import AgentContext
    from agenticapi.runtime.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Result of harness-controlled code execution.

    Attributes:
        output: The primary output from execution.
        generated_code: The code that was executed.
        reasoning: Optional LLM reasoning for the generated code.
        trace: The audit trace for this execution.
        sandbox_result: The raw sandbox execution result.
    """

    output: Any
    generated_code: str
    reasoning: str | None = None
    trace: ExecutionTrace | None = None
    sandbox_result: SandboxResult | None = None


class HarnessEngine:
    """Central harness engine orchestrating safe code execution.

    All agent operations pass through the HarnessEngine, which ensures:
    - Policy compliance via PolicyEvaluator
    - Code safety via static AST analysis
    - Isolated execution via SandboxRuntime
    - Full audit trail via AuditRecorder

    Example:
        engine = HarnessEngine(
            policies=[CodePolicy(denied_modules=["os"]), DataPolicy(deny_ddl=True)],
        )
        result = await engine.execute(
            intent_raw="Show order count",
            intent_action="read",
            intent_domain="order",
            generated_code="result = db.query('SELECT COUNT(*) FROM orders')",
            endpoint_name="orders",
        )
    """

    def __init__(
        self,
        *,
        policies: list[Policy] | None = None,
        sandbox: ProcessSandbox | None = None,
        audit_recorder: AuditRecorder | None = None,
        approval_workflow: ApprovalWorkflow | None = None,
        monitors: list[ExecutionMonitor] | None = None,
        validators: list[ResultValidator] | None = None,
    ) -> None:
        """Initialize the harness engine.

        Args:
            policies: List of policies to enforce. If None, no policy checks.
            sandbox: Sandbox runtime for code execution. If None, a
                ProcessSandbox is created with default limits.
            audit_recorder: Recorder for audit traces. If None, a default
                in-memory recorder is created.
            approval_workflow: Optional approval workflow for human-in-the-loop
                control. If provided, operations matching approval rules will
                raise ApprovalRequired.
            monitors: Optional list of execution monitors to run after sandbox
                execution. Monitors check resource usage and output size.
            validators: Optional list of result validators to run after
                monitors. Validators check output correctness.
        """
        self._evaluator = PolicyEvaluator(policies=policies)
        self._sandbox = sandbox or ProcessSandbox()
        self._audit_recorder = audit_recorder or AuditRecorder()
        self._approval: ApprovalWorkflow | None = approval_workflow
        self._monitors: list[ExecutionMonitor] = monitors or []
        self._validators: list[ResultValidator] = validators or []

    @property
    def audit_recorder(self) -> AuditRecorder:
        """Access the audit recorder for retrieving traces."""
        return self._audit_recorder

    @property
    def evaluator(self) -> PolicyEvaluator:
        """Access the policy evaluator."""
        return self._evaluator

    async def execute(
        self,
        *,
        intent_raw: str,
        intent_action: str,
        intent_domain: str,
        generated_code: str,
        reasoning: str | None = None,
        endpoint_name: str = "",
        context: AgentContext | None = None,
        tools: ToolRegistry | None = None,
        sandbox_data: dict[str, object] | None = None,
    ) -> ExecutionResult:
        """Execute generated code through the full harness pipeline.

        Runs policy evaluation, static analysis, sandbox execution,
        and audit recording in sequence.

        Args:
            intent_raw: The original natural language request.
            intent_action: The classified action type.
            intent_domain: The domain of the request.
            generated_code: The Python code to evaluate and execute.
            reasoning: Optional LLM reasoning for the code.
            endpoint_name: Name of the agent endpoint.
            context: Optional agent execution context.
            tools: Optional tool registry for sandbox execution.

        Returns:
            ExecutionResult with the output and audit trace.

        Raises:
            PolicyViolation: If any policy denies the code or static
                analysis finds safety violations.
            CodeExecutionError: If sandbox execution fails.
            SandboxViolation: If sandbox detects a security violation.
        """
        trace_id = uuid.uuid4().hex
        start_time = time.monotonic()
        timestamp = datetime.now(tz=UTC)

        trace = ExecutionTrace(
            trace_id=trace_id,
            endpoint_name=endpoint_name,
            timestamp=timestamp,
            intent_raw=intent_raw,
            intent_action=intent_action,
            generated_code=generated_code,
            reasoning=reasoning,
        )

        logger.info(
            "harness_execute_start",
            trace_id=trace_id,
            endpoint_name=endpoint_name,
            intent_action=intent_action,
            code_lines=generated_code.count("\n") + 1,
        )

        from agenticapi.observability import (
            AgenticAPIAttributes,
            SpanNames,
            get_tracer,
        )

        tracer = get_tracer()

        try:
            # Step 1: Policy evaluation
            with tracer.start_as_current_span(SpanNames.POLICY_EVALUATE.value) as policy_span:
                evaluation = self._evaluator.evaluate(
                    code=generated_code,
                    intent_action=intent_action,
                    intent_domain=intent_domain,
                )
                policy_span.set_attribute(AgenticAPIAttributes.POLICY_ALLOWED.value, evaluation.allowed)
                if evaluation.violations:
                    policy_span.set_attribute(
                        AgenticAPIAttributes.POLICY_VIOLATIONS.value,
                        "; ".join(evaluation.violations)[:500],
                    )
            trace.policy_evaluations = [
                {
                    "policy_name": r.policy_name,
                    "allowed": r.allowed,
                    "violations": r.violations,
                    "warnings": r.warnings,
                }
                for r in evaluation.results
            ]

            # Step 2: Static analysis
            with tracer.start_as_current_span(SpanNames.STATIC_ANALYSIS.value) as static_span:
                denied_modules: list[str] = []
                for policy in self._evaluator.policies:
                    from agenticapi.harness.policy.code_policy import CodePolicy

                    if isinstance(policy, CodePolicy):
                        denied_modules = policy.denied_modules
                        break

                safety_result = check_code_safety(
                    generated_code,
                    denied_modules=denied_modules or None,
                    deny_eval_exec=True,
                    deny_dynamic_import=True,
                )

                if not safety_result.safe:
                    violation_descriptions = [v.description for v in safety_result.violations if v.severity == "error"]
                    violation_summary = "; ".join(violation_descriptions)
                    static_span.set_attribute(AgenticAPIAttributes.POLICY_VIOLATIONS.value, violation_summary[:500])
                    logger.warning(
                        "harness_static_analysis_failed",
                        trace_id=trace_id,
                        violations=violation_descriptions,
                    )
                    raise PolicyViolation(
                        policy="static_analysis",
                        violation=violation_summary,
                        generated_code=generated_code,
                    )

            # Step 3: Approval check
            if self._approval is not None:
                rule = self._approval.check_approval_required(
                    intent_action=intent_action,
                    intent_domain=intent_domain,
                )
                if rule is not None:
                    try:
                        with tracer.start_as_current_span(SpanNames.APPROVAL_WAIT.value) as approval_span:
                            approval_span.set_attribute(AgenticAPIAttributes.APPROVAL_REQUIRED.value, True)
                            await self._approval.create_request(
                                rule=rule,
                                trace_id=trace_id,
                                intent_raw=intent_raw,
                                intent_action=intent_action,
                                intent_domain=intent_domain,
                                generated_code=generated_code,
                            )
                    except ApprovalRequired as exc:
                        trace.approval_request_id = exc.request_id
                        raise

            # Step 4: Sandbox execution (with pre-fetched data injected)
            sandbox_result: SandboxResult | None = None
            with tracer.start_as_current_span(SpanNames.SANDBOX_EXECUTE.value) as sandbox_span:
                sandbox_span.set_attribute(
                    AgenticAPIAttributes.SANDBOX_BACKEND.value,
                    type(self._sandbox).__name__,
                )
                sandbox_start = time.monotonic()
                async with self._sandbox as sandbox:
                    sandbox_result = await sandbox.execute(
                        code=generated_code,
                        tools=tools,
                        resource_limits=ResourceLimits(),
                        sandbox_data=sandbox_data,
                    )
                sandbox_span.set_attribute(
                    AgenticAPIAttributes.SANDBOX_DURATION_MS.value,
                    (time.monotonic() - sandbox_start) * 1000,
                )

            # Step 5: Post-execution monitors
            for monitor in self._monitors:
                monitor_result = await monitor.on_execution_complete(
                    sandbox_result,
                    code=generated_code,
                )
                if not monitor_result.passed:
                    violation_msg = "; ".join(monitor_result.violations)
                    raise SandboxViolation(f"Monitor violation: {violation_msg}")

            # Step 6: Post-execution validators
            for validator in self._validators:
                validation = await validator.validate(
                    sandbox_result,
                    code=generated_code,
                    intent_action=intent_action,
                )
                if not validation.valid:
                    error_msg = "; ".join(validation.errors)
                    raise SandboxViolation(f"Validation failed: {error_msg}")

            trace.execution_result = sandbox_result.return_value if sandbox_result else None
            duration_ms = (time.monotonic() - start_time) * 1000
            trace.execution_duration_ms = duration_ms

            logger.info(
                "harness_execute_complete",
                trace_id=trace_id,
                duration_ms=duration_ms,
            )

            result = ExecutionResult(
                output=sandbox_result.return_value if sandbox_result else None,
                generated_code=generated_code,
                reasoning=reasoning,
                trace=trace,
                sandbox_result=sandbox_result,
            )

        except Exception as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            trace.execution_duration_ms = duration_ms
            trace.error = str(exc)

            logger.error(
                "harness_execute_failed",
                trace_id=trace_id,
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=duration_ms,
            )

            # Record the failed trace before re-raising.  Wrap in
            # try/except so a recorder failure does not mask the
            # original exception.
            try:
                await self._audit_recorder.record(trace)
            except Exception:
                logger.exception("audit_record_failed_on_error_path", trace_id=trace_id)
            raise

        # Step 7: Record audit trace
        await self._audit_recorder.record(trace)

        return result

    def evaluate_intent_text(
        self,
        *,
        intent_text: str,
        intent_action: str = "",
        intent_domain: str = "",
    ) -> None:
        """Run input-scanning policies on raw intent text before the LLM fires.

        Called by the framework at the top of ``_execute_intent`` — the
        earliest point after the intent string is extracted from the
        request body and before any LLM call, code generation, or
        handler execution. This ensures ``PromptInjectionPolicy`` and
        ``PIIPolicy`` block unsafe input at the LLM boundary.

        Raises :class:`~agenticapi.exceptions.PolicyViolation` if any
        policy denies the text. On success, returns silently.

        Policies that don't override
        :meth:`~agenticapi.harness.policy.base.Policy.evaluate_intent_text`
        default to allow, so adding this call has zero effect on policies
        like ``CodePolicy`` or ``DataPolicy`` whose domain is generated
        code, not user text.
        """
        self._evaluator.evaluate_intent_text(
            intent_text=intent_text,
            intent_action=intent_action,
            intent_domain=intent_domain,
        )

    async def call_tool(
        self,
        *,
        tool: Any,
        arguments: dict[str, Any],
        intent_raw: str = "",
        intent_action: str = "",
        intent_domain: str = "",
        endpoint_name: str = "",
        context: AgentContext | None = None,
    ) -> ExecutionResult:
        """Invoke a registered tool directly (Phase E4 tool-first path).

        Skips code generation and sandbox execution entirely. The
        only policy pass that runs is
        :meth:`PolicyEvaluator.evaluate_tool_call` — AST checks and
        sandbox safety nets are irrelevant when we're calling a
        *pre-registered* Python function whose implementation we
        control. In exchange the caller gets roughly an order of
        magnitude lower latency and removes a whole class of
        code-gen failures from the hot path.

        Args:
            tool: The :class:`~agenticapi.runtime.tools.base.Tool` to
                invoke. Typically obtained from the app's
                :class:`ToolRegistry` via the name the LLM emitted.
            arguments: Keyword arguments for the tool call, usually
                coming straight from
                :attr:`agenticapi.runtime.llm.base.ToolCall.arguments`.
            intent_raw: The original intent string for the audit
                trace.
            intent_action: Classified action for policy evaluation
                (``read``/``write``/etc.).
            intent_domain: Classified domain.
            endpoint_name: Endpoint whose request triggered this
                call, for the audit record.
            context: Optional :class:`AgentContext` — currently
                unused by the tool-first path but accepted for
                symmetry with :meth:`execute`.

        Returns:
            :class:`ExecutionResult` with the tool's return value,
            no generated code, and a fully populated audit trace.

        Raises:
            PolicyViolation: If any policy's
                :meth:`evaluate_tool_call` hook denies the call.
            ToolError: If the tool's own invocation fails.
        """
        del context
        trace_id = uuid.uuid4().hex
        start = time.monotonic()
        timestamp = datetime.now(tz=UTC)
        tool_name = tool.definition.name

        trace = ExecutionTrace(
            trace_id=trace_id,
            endpoint_name=endpoint_name,
            timestamp=timestamp,
            intent_raw=intent_raw,
            intent_action=intent_action,
            generated_code=f"# tool-first call: {tool_name}({arguments})",
        )

        logger.info(
            "harness_tool_call_start",
            trace_id=trace_id,
            tool=tool_name,
            intent_action=intent_action,
        )

        try:
            evaluation = self._evaluator.evaluate_tool_call(
                tool_name=tool_name,
                arguments=arguments,
                intent_action=intent_action,
                intent_domain=intent_domain,
            )
            trace.policy_evaluations = [
                {
                    "policy_name": r.policy_name,
                    "allowed": r.allowed,
                    "violations": r.violations,
                    "warnings": r.warnings,
                }
                for r in evaluation.results
            ]

            invocation_start = time.monotonic()
            output = await tool.invoke(**arguments)
            tool_duration_ms = (time.monotonic() - invocation_start) * 1000
            trace.execution_result = output
            trace.execution_duration_ms = (time.monotonic() - start) * 1000

            logger.info(
                "harness_tool_call_complete",
                trace_id=trace_id,
                tool=tool_name,
                duration_ms=trace.execution_duration_ms,
                tool_duration_ms=tool_duration_ms,
            )

        except PolicyViolation:
            trace.execution_duration_ms = (time.monotonic() - start) * 1000
            trace.error = f"Policy denied tool call {tool_name}"
            await self._audit_recorder.record(trace)
            raise
        except Exception as exc:
            trace.execution_duration_ms = (time.monotonic() - start) * 1000
            trace.error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "harness_tool_call_failed",
                trace_id=trace_id,
                tool=tool_name,
                error=str(exc),
            )
            await self._audit_recorder.record(trace)
            raise

        await self._audit_recorder.record(trace)
        return ExecutionResult(
            output=output,
            generated_code=trace.generated_code,
            reasoning=None,
            trace=trace,
            sandbox_result=None,
        )
