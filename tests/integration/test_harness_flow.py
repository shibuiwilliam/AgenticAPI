"""Integration test: harness blocks dangerous code."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import ApprovalRequired, PolicyViolation
from agenticapi.harness.approval.rules import ApprovalRule
from agenticapi.harness.approval.workflow import ApprovalWorkflow
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.harness.sandbox.base import ResourceLimits
from agenticapi.harness.sandbox.monitors import ResourceMonitor
from agenticapi.harness.sandbox.validators import OutputTypeValidator
from agenticapi.runtime.context import AgentContext


class TestHarnessBlocksDangerousCode:
    async def test_blocks_denied_import(self) -> None:
        """Harness rejects code that imports a denied module."""
        engine = HarnessEngine(
            policies=[CodePolicy(denied_modules=["os"])],
        )
        context = AgentContext(trace_id="test", endpoint_name="test")

        with pytest.raises(PolicyViolation, match="os"):
            await engine.execute(
                intent_raw="test",
                intent_action="read",
                intent_domain="general",
                generated_code="import os\nos.system('ls')",
                endpoint_name="test",
                context=context,
            )

    async def test_blocks_ddl_via_data_policy(self) -> None:
        """Harness rejects code with DDL statements."""
        engine = HarnessEngine(
            policies=[DataPolicy(deny_ddl=True)],
        )
        context = AgentContext(trace_id="test", endpoint_name="test")

        with pytest.raises(PolicyViolation, match="DDL"):
            await engine.execute(
                intent_raw="drop the table",
                intent_action="write",
                intent_domain="general",
                generated_code="db.execute('DROP TABLE users')",
                endpoint_name="test",
                context=context,
            )

    async def test_blocks_eval_via_static_analysis(self) -> None:
        """Harness static analysis catches eval() even without CodePolicy."""
        engine = HarnessEngine(policies=[])
        context = AgentContext(trace_id="test", endpoint_name="test")

        with pytest.raises(PolicyViolation, match="static_analysis"):
            await engine.execute(
                intent_raw="test",
                intent_action="read",
                intent_domain="general",
                generated_code="x = eval('1+1')",
                endpoint_name="test",
                context=context,
            )

    async def test_safe_code_executes_successfully(self) -> None:
        """Harness allows safe code to execute and returns result."""
        engine = HarnessEngine(policies=[])
        context = AgentContext(trace_id="test", endpoint_name="test")

        result = await engine.execute(
            intent_raw="compute sum",
            intent_action="read",
            intent_domain="general",
            generated_code="result = 2 + 3",
            endpoint_name="test",
            context=context,
        )

        assert result.output == 5
        assert result.generated_code == "result = 2 + 3"
        assert result.trace is not None
        assert result.trace.trace_id is not None

    async def test_audit_trace_recorded_on_success(self) -> None:
        """Successful execution produces an audit trace."""
        engine = HarnessEngine(policies=[])
        context = AgentContext(trace_id="test", endpoint_name="orders")

        await engine.execute(
            intent_raw="count orders",
            intent_action="read",
            intent_domain="order",
            generated_code="result = 100",
            endpoint_name="orders",
            context=context,
        )

        records = engine.audit_recorder.get_records(endpoint_name="orders")
        assert len(records) == 1
        assert records[0].intent_raw == "count orders"
        assert records[0].generated_code == "result = 100"

    async def test_audit_trace_recorded_on_failure(self) -> None:
        """Failed execution still records an audit trace."""
        engine = HarnessEngine(
            policies=[CodePolicy(denied_modules=["os"])],
        )
        context = AgentContext(trace_id="test", endpoint_name="test")

        with pytest.raises(PolicyViolation):
            await engine.execute(
                intent_raw="test",
                intent_action="read",
                intent_domain="general",
                generated_code="import os",
                endpoint_name="test",
                context=context,
            )

        records = engine.audit_recorder.get_records()
        assert len(records) == 1
        assert records[0].error is not None


class TestHarnessApprovalIntegration:
    async def test_approval_workflow_blocks_write(self) -> None:
        """Harness raises ApprovalRequired when approval rule matches."""
        rule = ApprovalRule(
            name="write_approval",
            require_for_actions=["write"],
            approvers=["admin"],
        )
        workflow = ApprovalWorkflow(rules=[rule])
        engine = HarnessEngine(
            policies=[],
            approval_workflow=workflow,
        )
        context = AgentContext(trace_id="test", endpoint_name="test")

        with pytest.raises(ApprovalRequired) as exc_info:
            await engine.execute(
                intent_raw="delete orders",
                intent_action="write",
                intent_domain="order",
                generated_code="result = 42",
                endpoint_name="test",
                context=context,
            )

        assert exc_info.value.request_id is not None
        assert exc_info.value.approvers == ["admin"]

        # Audit trace should be recorded
        records = engine.audit_recorder.get_records()
        assert len(records) == 1
        assert records[0].approval_request_id == exc_info.value.request_id

    async def test_approval_not_required_for_read(self) -> None:
        """Read operations pass through without approval."""
        rule = ApprovalRule(name="write_only", require_for_actions=["write"])
        workflow = ApprovalWorkflow(rules=[rule])
        engine = HarnessEngine(policies=[], approval_workflow=workflow)
        context = AgentContext(trace_id="test", endpoint_name="test")

        result = await engine.execute(
            intent_raw="count items",
            intent_action="read",
            intent_domain="order",
            generated_code="result = 42",
            endpoint_name="test",
            context=context,
        )

        assert result.output == 42


class TestHarnessMonitorsIntegration:
    async def test_monitors_run_after_execution(self) -> None:
        """Monitors validate post-execution metrics."""
        monitor = ResourceMonitor(
            limits=ResourceLimits(max_cpu_seconds=30, max_memory_mb=512, max_execution_time_seconds=60)
        )
        engine = HarnessEngine(policies=[], monitors=[monitor])
        context = AgentContext(trace_id="test", endpoint_name="test")

        result = await engine.execute(
            intent_raw="compute",
            intent_action="read",
            intent_domain="general",
            generated_code="result = 1 + 1",
            endpoint_name="test",
            context=context,
        )

        assert result.output == 2

    async def test_validators_run_after_monitors(self) -> None:
        """Validators check output after execution."""
        validator = OutputTypeValidator()
        engine = HarnessEngine(policies=[], validators=[validator])
        context = AgentContext(trace_id="test", endpoint_name="test")

        result = await engine.execute(
            intent_raw="compute",
            intent_action="read",
            intent_domain="general",
            generated_code="result = {'key': 'value'}",
            endpoint_name="test",
            context=context,
        )

        assert result.output == {"key": "value"}
