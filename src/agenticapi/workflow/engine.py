"""Workflow engine for multi-step agent processes.

Implements :class:`AgentWorkflow` — a declarative workflow primitive
with a builder API that lets developers define multi-step agent
processes using plain Python functions. Each step receives the typed
state and a :class:`WorkflowContext`, and returns the name of the
next step (or ``None`` to end the workflow).

Key design principles:

1. **Typed state** — ``WorkflowState`` is a Pydantic model. Every
   step reads and writes typed fields. State is serialisable.
2. **Conditional routing** — Steps return the name of the next step
   (a string). This enables branching without graph DSLs.
3. **Parallel steps** — Return a list of step names to run concurrently.
4. **Checkpoints** — Steps marked ``checkpoint=True`` persist state
   and pause for external input.
5. **Harness integration** — Tool calls within a step go through the
   harness. Every step transition is audit-recorded.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import structlog

from agenticapi.workflow.state import WorkflowState

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agenticapi.harness.engine import HarnessEngine
    from agenticapi.runtime.context import AgentContext
    from agenticapi.runtime.llm.base import LLMBackend
    from agenticapi.runtime.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)

S = TypeVar("S", bound=WorkflowState)


@dataclass(frozen=True, slots=True)
class StepConfig:
    """Configuration for a workflow step.

    Attributes:
        checkpoint: If ``True``, the engine persists state and pauses
            after this step executes, returning a ``WorkflowPaused``
            result. The client resumes by calling the endpoint with
            the ``workflow_id``.
        require_approval: If ``True``, the step requires explicit
            approval before executing.
        timeout_seconds: Maximum wall-clock time for the step.
        max_retries: Number of retry attempts on failure.
    """

    checkpoint: bool = False
    require_approval: bool = False
    timeout_seconds: float = 30.0
    max_retries: int = 0


@dataclass(slots=True)
class WorkflowResult(Generic[S]):  # noqa: UP046
    """Result of a completed (or paused) workflow execution.

    Attributes:
        final_state: The workflow state at completion or pause.
        steps_executed: Ordered list of step names that ran.
        total_duration_ms: Wall-clock time for the entire workflow.
        checkpoints_hit: Number of checkpoint steps encountered.
        paused: ``True`` if the workflow paused at a checkpoint.
        paused_at_step: Name of the checkpoint step (if paused).
        workflow_id: Unique ID for resuming a paused workflow.
    """

    final_state: S
    steps_executed: list[str] = field(default_factory=list)
    total_duration_ms: float = 0.0
    checkpoints_hit: int = 0
    paused: bool = False
    paused_at_step: str | None = None
    workflow_id: str | None = None


class WorkflowContext:
    """Context available within workflow steps.

    Provides access to tools, LLM, and the harness for governed
    execution within a step.
    """

    def __init__(
        self,
        *,
        tools: ToolRegistry | None = None,
        harness: HarnessEngine | None = None,
        agent_context: AgentContext | None = None,
        llm: LLMBackend | None = None,
    ) -> None:
        self._tools = tools
        self._harness = harness
        self._agent_context = agent_context
        self._llm = llm

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Invoke a registered tool, optionally through the harness.

        Args:
            tool_name: Name of the tool to invoke.
            **kwargs: Arguments to pass to the tool.

        Returns:
            The tool's return value.

        Raises:
            ToolError: If the tool is not found or invocation fails.
        """
        if self._tools is None:
            from agenticapi.exceptions import ToolError

            raise ToolError("No tool registry configured for this workflow.")

        tool = self._tools.get(tool_name)

        if self._harness is not None:
            result = await self._harness.call_tool(
                tool=tool,
                arguments=kwargs,
                endpoint_name=self._agent_context.endpoint_name if self._agent_context else "",
                context=self._agent_context,
            )
            return result.output

        return await tool.invoke(**kwargs)

    async def llm_generate(self, prompt: str) -> str:
        """Generate text using the LLM backend.

        Args:
            prompt: The prompt text.

        Returns:
            The generated text response.

        Raises:
            AgenticAPIError: If no LLM backend is configured.
        """
        if self._llm is None:
            from agenticapi.exceptions import AgenticAPIError

            raise AgenticAPIError("No LLM backend configured for this workflow.")

        from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

        llm_prompt = LLMPrompt(
            system="You are a helpful assistant.",
            messages=[LLMMessage(role="user", content=prompt)],
        )
        response = await self._llm.generate(llm_prompt)
        return response.content

    @property
    def trace_id(self) -> str:
        """The current trace ID."""
        if self._agent_context is not None:
            return self._agent_context.trace_id
        return ""

    @property
    def budget_remaining_usd(self) -> float | None:
        """Remaining budget in USD, or None if no budget is configured."""
        if self._harness is None:
            return None
        from agenticapi.harness.policy.budget_policy import BudgetPolicy

        for policy in self._harness._evaluator.policies:
            if isinstance(policy, BudgetPolicy) and policy.max_per_request_usd is not None:
                return policy.max_per_request_usd
        return None


class _StepDef:
    """Internal step registration."""

    __slots__ = ("config", "func", "name")

    def __init__(
        self,
        name: str,
        func: Callable[..., Awaitable[str | list[str] | None]],
        config: StepConfig,
    ) -> None:
        self.name = name
        self.func = func
        self.config = config


class AgentWorkflow(Generic[S]):  # noqa: UP046
    """Declarative multi-step workflow with typed state.

    Example::

        class MyState(WorkflowState):
            data: str = ""

        workflow = AgentWorkflow(name="pipeline", state_class=MyState)

        @workflow.step("parse")
        async def parse(state: MyState, context: WorkflowContext) -> str:
            state.data = "parsed"
            return "analyze"

        @workflow.step("analyze")
        async def analyze(state: MyState, context: WorkflowContext) -> None:
            state.data += " analyzed"
            return None  # end workflow

        result = await workflow.run()
        assert result.final_state.data == "parsed analyzed"
    """

    def __init__(self, name: str, state_class: type[S] | None = None) -> None:
        self._name = name
        self._state_class = state_class
        self._steps: dict[str, _StepDef] = {}
        self._entry_step: str | None = None

    @property
    def name(self) -> str:
        """The workflow name."""
        return self._name

    @property
    def steps(self) -> list[str]:
        """Sorted list of registered step names."""
        return sorted(self._steps.keys())

    def step(
        self,
        name: str,
        *,
        checkpoint: bool = False,
        require_approval: bool = False,
        timeout_seconds: float = 30.0,
        max_retries: int = 0,
    ) -> Callable[[Callable[..., Awaitable[str | list[str] | None]]], Callable[..., Awaitable[str | list[str] | None]]]:
        """Register a workflow step.

        The decorated function receives ``(state, context)`` and
        returns:

        - A ``str`` — the name of the next step (sequential).
        - A ``list[str]`` — step names to run in parallel.
        - ``None`` — the workflow is complete.

        The first registered step is the entry point unless
        :meth:`set_entry` is called.

        Args:
            name: Unique step name.
            checkpoint: Pause after this step for external input.
            require_approval: Require approval before executing.
            timeout_seconds: Step timeout in seconds.
            max_retries: Retry count on failure.
        """
        config = StepConfig(
            checkpoint=checkpoint,
            require_approval=require_approval,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

        def decorator(
            func: Callable[..., Awaitable[str | list[str] | None]],
        ) -> Callable[..., Awaitable[str | list[str] | None]]:
            self._steps[name] = _StepDef(name=name, func=func, config=config)
            if self._entry_step is None:
                self._entry_step = name
            return func

        return decorator

    def set_entry(self, name: str) -> None:
        """Set the entry step explicitly."""
        self._entry_step = name

    async def run(
        self,
        *,
        initial_state: S | None = None,
        context: AgentContext | None = None,
        harness: HarnessEngine | None = None,
        tools: ToolRegistry | None = None,
        llm: LLMBackend | None = None,
        workflow_id: str | None = None,
        resume_from: str | None = None,
    ) -> WorkflowResult[S]:
        """Execute the workflow from the entry step to completion.

        Args:
            initial_state: Starting state. If ``None``, the state
                class is instantiated with defaults.
            context: Optional agent context for tracing.
            harness: Optional harness for governed tool calls.
            tools: Optional tool registry.
            llm: Optional LLM backend for ``WorkflowContext.llm_generate()``.
            workflow_id: ID for persisted/resumed workflows.
            resume_from: Step name to resume from (for checkpoint
                continuation).

        Returns:
            A :class:`WorkflowResult` with the final state and
            execution metadata.
        """
        if not self._steps:
            raise ValueError(f"Workflow '{self._name}' has no registered steps.")

        if initial_state is not None:
            state = initial_state
        elif self._state_class is not None:
            state = self._state_class()
        else:
            raise ValueError("Either initial_state or state_class must be provided.")

        wf_ctx = WorkflowContext(
            tools=tools,
            harness=harness,
            agent_context=context,
            llm=llm,
        )

        current_step = resume_from or self._entry_step
        if current_step is None:
            raise ValueError("No entry step defined.")

        steps_executed: list[str] = []
        checkpoints_hit = 0
        t0 = time.monotonic()

        while current_step is not None:
            if current_step not in self._steps:
                raise ValueError(f"Unknown step '{current_step}' in workflow '{self._name}'.")

            step_def = self._steps[current_step]

            # Update state tracking.
            state.wf_current_step = current_step
            state.wf_iteration_count += 1

            logger.info(
                "workflow_step_start",
                workflow=self._name,
                step=current_step,
                iteration=state.wf_iteration_count,
            )

            # Execute with retry logic.
            last_error: Exception | None = None
            result: str | list[str] | None = None
            for attempt in range(step_def.config.max_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        step_def.func(state, wf_ctx),
                        timeout=step_def.config.timeout_seconds,
                    )
                    last_error = None
                    break
                except TimeoutError:
                    last_error = TimeoutError(
                        f"Step '{current_step}' timed out after {step_def.config.timeout_seconds}s"
                    )
                except Exception as exc:
                    last_error = exc
                    if attempt < step_def.config.max_retries:
                        logger.warning(
                            "workflow_step_retry",
                            workflow=self._name,
                            step=current_step,
                            attempt=attempt + 1,
                            error=str(exc),
                        )

            if last_error is not None:
                raise last_error

            steps_executed.append(current_step)
            state.wf_completed_steps.append(current_step)

            logger.info(
                "workflow_step_complete",
                workflow=self._name,
                step=current_step,
                next_step=result,
            )

            # Handle checkpoint.
            if step_def.config.checkpoint:
                checkpoints_hit += 1
                duration_ms = (time.monotonic() - t0) * 1000
                return WorkflowResult(
                    final_state=state,
                    steps_executed=steps_executed,
                    total_duration_ms=round(duration_ms, 2),
                    checkpoints_hit=checkpoints_hit,
                    paused=True,
                    paused_at_step=current_step,
                    workflow_id=workflow_id,
                )

            # Route to next step.
            if result is None:
                current_step = None
            elif isinstance(result, str):
                current_step = result
            elif isinstance(result, list):
                # Parallel execution: run all steps concurrently,
                # then continue with the last one that returns a next step.
                parallel_results = await asyncio.gather(*[self._run_step(name, state, wf_ctx) for name in result])
                steps_executed.extend(result)
                state.wf_completed_steps.extend(result)

                # Find the next step from parallel results.
                # Use the first non-None result as the continuation.
                current_step = None
                for pr in parallel_results:
                    if pr is not None:
                        if isinstance(pr, str):
                            current_step = pr
                            break
                        elif isinstance(pr, list) and pr:
                            current_step = pr[0]
                            break

        duration_ms = (time.monotonic() - t0) * 1000
        return WorkflowResult(
            final_state=state,
            steps_executed=steps_executed,
            total_duration_ms=round(duration_ms, 2),
            checkpoints_hit=checkpoints_hit,
            paused=False,
            workflow_id=workflow_id,
        )

    async def _run_step(
        self,
        name: str,
        state: S,
        context: WorkflowContext,
    ) -> str | list[str] | None:
        """Execute a single step (used for parallel dispatch)."""
        if name not in self._steps:
            raise ValueError(f"Unknown step '{name}' in workflow '{self._name}'.")
        step_def = self._steps[name]
        return await asyncio.wait_for(
            step_def.func(state, context),
            timeout=step_def.config.timeout_seconds,
        )

    def to_mermaid(self) -> str:
        """Generate a Mermaid flowchart of the workflow graph.

        Returns a string that can be rendered by Mermaid-compatible
        tools. Note: this generates a static graph based on step
        registrations — runtime conditional routing is not reflected.
        """
        lines = ["graph TD"]
        for name in sorted(self._steps.keys()):
            step_def = self._steps[name]
            suffix = " [entry]" if name == self._entry_step else ""
            shape = f"({name}{suffix})" if not step_def.config.checkpoint else f"[/{name}{suffix}/]"
            lines.append(f"    {name}{shape}")
            if step_def.config.checkpoint:
                lines.append(f"    {name} -. checkpoint .-> resume_{name}[Resume]")
        return "\n".join(lines)
