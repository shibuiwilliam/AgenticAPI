"""Tests for the workflow engine."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import Field

from agenticapi.workflow.engine import AgentWorkflow, WorkflowContext, WorkflowResult
from agenticapi.workflow.state import WorkflowState
from agenticapi.workflow.store import InMemoryWorkflowStore, SqliteWorkflowStore

# ---------------------------------------------------------------------------
# Test state classes
# ---------------------------------------------------------------------------


class SimpleState(WorkflowState):
    """State for linear workflow tests."""

    data: str = ""
    count: int = 0


class BranchState(WorkflowState):
    """State for branching tests."""

    value: int = 0
    path_taken: str = ""


class ParallelState(WorkflowState):
    """State for parallel execution tests."""

    results: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Tests: Linear Workflow
# ---------------------------------------------------------------------------


class TestLinearWorkflow:
    """Three steps A -> B -> C in sequence."""

    async def test_three_step_linear(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="linear", state_class=SimpleState)

        @workflow.step("step_a")
        async def step_a(state: SimpleState, ctx: WorkflowContext) -> str:
            state.data += "A"
            state.count += 1
            return "step_b"

        @workflow.step("step_b")
        async def step_b(state: SimpleState, ctx: WorkflowContext) -> str:
            state.data += "B"
            state.count += 1
            return "step_c"

        @workflow.step("step_c")
        async def step_c(state: SimpleState, ctx: WorkflowContext) -> None:
            state.data += "C"
            state.count += 1
            return None

        result = await workflow.run()

        assert isinstance(result, WorkflowResult)
        assert result.final_state.data == "ABC"
        assert result.final_state.count == 3
        assert result.steps_executed == ["step_a", "step_b", "step_c"]
        assert result.total_duration_ms > 0
        assert result.paused is False
        assert result.checkpoints_hit == 0


class TestConditionalBranching:
    """Step A returns different next steps based on state."""

    async def test_branch_to_b(self) -> None:
        workflow: AgentWorkflow[BranchState] = AgentWorkflow(name="branch", state_class=BranchState)

        @workflow.step("decide")
        async def decide(state: BranchState, ctx: WorkflowContext) -> str:
            if state.value > 10:
                return "high"
            return "low"

        @workflow.step("high")
        async def high(state: BranchState, ctx: WorkflowContext) -> None:
            state.path_taken = "high"
            return None

        @workflow.step("low")
        async def low(state: BranchState, ctx: WorkflowContext) -> None:
            state.path_taken = "low"
            return None

        # Test low path
        result = await workflow.run(initial_state=BranchState(value=5))
        assert result.final_state.path_taken == "low"
        assert result.steps_executed == ["decide", "low"]

    async def test_branch_to_high(self) -> None:
        workflow: AgentWorkflow[BranchState] = AgentWorkflow(name="branch", state_class=BranchState)

        @workflow.step("decide")
        async def decide(state: BranchState, ctx: WorkflowContext) -> str:
            if state.value > 10:
                return "high"
            return "low"

        @workflow.step("high")
        async def high(state: BranchState, ctx: WorkflowContext) -> None:
            state.path_taken = "high"
            return None

        @workflow.step("low")
        async def low(state: BranchState, ctx: WorkflowContext) -> None:
            state.path_taken = "low"
            return None

        # Test high path
        result = await workflow.run(initial_state=BranchState(value=20))
        assert result.final_state.path_taken == "high"
        assert result.steps_executed == ["decide", "high"]


class TestParallelSteps:
    """Step returns a list of step names for parallel execution."""

    async def test_parallel_execution(self) -> None:
        workflow: AgentWorkflow[ParallelState] = AgentWorkflow(name="parallel", state_class=ParallelState)

        @workflow.step("start")
        async def start(state: ParallelState, ctx: WorkflowContext) -> list[str]:
            return ["task_a", "task_b"]

        @workflow.step("task_a")
        async def task_a(state: ParallelState, ctx: WorkflowContext) -> None:
            state.results.append("A")
            return None

        @workflow.step("task_b")
        async def task_b(state: ParallelState, ctx: WorkflowContext) -> None:
            state.results.append("B")
            return None

        result = await workflow.run()
        assert "A" in result.final_state.results
        assert "B" in result.final_state.results
        assert "start" in result.steps_executed
        assert "task_a" in result.steps_executed
        assert "task_b" in result.steps_executed


class TestCheckpoint:
    """Step with checkpoint=True pauses the workflow."""

    async def test_checkpoint_pauses(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="checkpoint", state_class=SimpleState)

        @workflow.step("step_a")
        async def step_a(state: SimpleState, ctx: WorkflowContext) -> str:
            state.data += "A"
            return "review"

        @workflow.step("review", checkpoint=True)
        async def review(state: SimpleState, ctx: WorkflowContext) -> str:
            state.data += "R"
            return "step_b"

        @workflow.step("step_b")
        async def step_b(state: SimpleState, ctx: WorkflowContext) -> None:
            state.data += "B"
            return None

        result = await workflow.run(workflow_id="wf-001")

        assert result.paused is True
        assert result.paused_at_step == "review"
        assert result.workflow_id == "wf-001"
        assert result.checkpoints_hit == 1
        assert result.final_state.data == "AR"
        assert result.steps_executed == ["step_a", "review"]

    async def test_resume_from_checkpoint(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="checkpoint", state_class=SimpleState)

        @workflow.step("step_a")
        async def step_a(state: SimpleState, ctx: WorkflowContext) -> str:
            state.data += "A"
            return "review"

        @workflow.step("review", checkpoint=True)
        async def review(state: SimpleState, ctx: WorkflowContext) -> str:
            state.data += "R"
            return "step_b"

        @workflow.step("step_b")
        async def step_b(state: SimpleState, ctx: WorkflowContext) -> None:
            state.data += "B"
            return None

        # First run — pauses at checkpoint.
        r1 = await workflow.run(workflow_id="wf-002")
        assert r1.paused is True

        # Resume from after the checkpoint step.
        r2 = await workflow.run(
            initial_state=r1.final_state,
            resume_from="step_b",
            workflow_id="wf-002",
        )
        assert r2.paused is False
        assert r2.final_state.data == "ARB"
        assert r2.steps_executed == ["step_b"]


class TestRetries:
    """Step with max_retries retries on failure."""

    async def test_retry_succeeds_on_second_attempt(self) -> None:
        attempt_count = 0

        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="retry", state_class=SimpleState)

        @workflow.step("flaky", max_retries=2)
        async def flaky(state: SimpleState, ctx: WorkflowContext) -> None:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise RuntimeError("transient error")
            state.data = "success"
            return None

        result = await workflow.run()
        assert result.final_state.data == "success"
        assert attempt_count == 2

    async def test_retry_exhausted_raises(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="retry", state_class=SimpleState)

        @workflow.step("always_fail", max_retries=1)
        async def always_fail(state: SimpleState, ctx: WorkflowContext) -> None:
            raise RuntimeError("permanent error")

        with pytest.raises(RuntimeError, match="permanent error"):
            await workflow.run()


class TestTimeout:
    """Step with timeout_seconds enforced."""

    async def test_step_timeout(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="timeout", state_class=SimpleState)

        @workflow.step("slow", timeout_seconds=0.1)
        async def slow(state: SimpleState, ctx: WorkflowContext) -> None:
            await asyncio.sleep(10)  # Will be cancelled by timeout
            return None

        with pytest.raises(asyncio.TimeoutError):
            await workflow.run()


class TestMermaidExport:
    """Workflow graph export to Mermaid format."""

    def test_mermaid_output(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="mermaid", state_class=SimpleState)

        @workflow.step("start")
        async def start(state: SimpleState, ctx: WorkflowContext) -> str:
            return "end"

        @workflow.step("end")
        async def end(state: SimpleState, ctx: WorkflowContext) -> None:
            return None

        mermaid = workflow.to_mermaid()
        assert "graph TD" in mermaid
        assert "end" in mermaid
        assert "start" in mermaid


class TestWorkflowContextLLM:
    """Test WorkflowContext.llm_generate()."""

    async def test_llm_generate_calls_backend(self) -> None:
        from agenticapi.runtime.llm.mock import MockBackend

        backend = MockBackend(responses=["Generated text."])
        ctx = WorkflowContext(llm=backend)
        result = await ctx.llm_generate("Summarize this")
        assert result == "Generated text."

    async def test_llm_generate_without_backend_raises(self) -> None:
        ctx = WorkflowContext()
        with pytest.raises(Exception, match="No LLM backend"):
            await ctx.llm_generate("test")

    def test_budget_remaining_without_harness(self) -> None:
        ctx = WorkflowContext()
        assert ctx.budget_remaining_usd is None


class TestEdgeCases:
    """Edge cases and error handling."""

    async def test_empty_workflow_raises(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="empty", state_class=SimpleState)
        with pytest.raises(ValueError, match="no registered steps"):
            await workflow.run()

    async def test_unknown_step_raises(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="bad", state_class=SimpleState)

        @workflow.step("start")
        async def start(state: SimpleState, ctx: WorkflowContext) -> str:
            return "nonexistent"

        with pytest.raises(ValueError, match="Unknown step"):
            await workflow.run()

    def test_step_list(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="list", state_class=SimpleState)

        @workflow.step("b")
        async def b(state: SimpleState, ctx: WorkflowContext) -> None:
            return None

        @workflow.step("a")
        async def a(state: SimpleState, ctx: WorkflowContext) -> None:
            return None

        assert workflow.steps == ["a", "b"]

    async def test_set_entry(self) -> None:
        workflow: AgentWorkflow[SimpleState] = AgentWorkflow(name="entry", state_class=SimpleState)

        @workflow.step("first")
        async def first(state: SimpleState, ctx: WorkflowContext) -> str:
            state.data = "wrong"
            return None  # type: ignore[return-value]

        @workflow.step("second")
        async def second(state: SimpleState, ctx: WorkflowContext) -> None:
            state.data = "right"
            return None

        workflow.set_entry("second")
        result = await workflow.run()
        assert result.final_state.data == "right"


# ---------------------------------------------------------------------------
# Tests: WorkflowStore
# ---------------------------------------------------------------------------


class TestInMemoryWorkflowStore:
    """Tests for InMemoryWorkflowStore."""

    async def test_save_and_load(self) -> None:
        store = InMemoryWorkflowStore()
        await store.save("wf-1", "step_a", '{"data": "hello"}')
        result = await store.load("wf-1")
        assert result is not None
        assert result == ("step_a", '{"data": "hello"}')

    async def test_load_missing_returns_none(self) -> None:
        store = InMemoryWorkflowStore()
        assert await store.load("nonexistent") is None

    async def test_delete(self) -> None:
        store = InMemoryWorkflowStore()
        await store.save("wf-1", "step_a", "{}")
        await store.delete("wf-1")
        assert await store.load("wf-1") is None

    async def test_list_active(self) -> None:
        store = InMemoryWorkflowStore()
        await store.save("wf-2", "step_a", "{}")
        await store.save("wf-1", "step_b", "{}")
        active = await store.list_active()
        assert active == ["wf-1", "wf-2"]


class TestSqliteWorkflowStore:
    """Tests for SqliteWorkflowStore."""

    async def test_save_and_load(self, tmp_path: Any) -> None:
        store = SqliteWorkflowStore(path=tmp_path / "test.db")
        try:
            await store.save("wf-1", "step_a", '{"data": "hello"}')
            result = await store.load("wf-1")
            assert result == ("step_a", '{"data": "hello"}')
        finally:
            store.close()

    async def test_persistence_across_instances(self, tmp_path: Any) -> None:
        db_path = tmp_path / "persist.db"
        store1 = SqliteWorkflowStore(path=db_path)
        await store1.save("wf-1", "step_a", '{"data": "persisted"}')
        store1.close()

        store2 = SqliteWorkflowStore(path=db_path)
        result = await store2.load("wf-1")
        assert result == ("step_a", '{"data": "persisted"}')
        store2.close()

    async def test_delete_and_list(self, tmp_path: Any) -> None:
        store = SqliteWorkflowStore(path=tmp_path / "test.db")
        try:
            await store.save("wf-1", "a", "{}")
            await store.save("wf-2", "b", "{}")
            assert await store.list_active() == ["wf-1", "wf-2"]
            await store.delete("wf-1")
            assert await store.list_active() == ["wf-2"]
        finally:
            store.close()
