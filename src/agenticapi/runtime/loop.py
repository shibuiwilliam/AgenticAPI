"""Multi-turn agentic loop (ReAct pattern).

Implements the core agent reasoning loop: send prompt with tools to the
LLM, dispatch tool calls through the harness, feed results back to the
LLM, and repeat until the LLM returns a final text answer or the
iteration limit is reached.

Every iteration is harness-governed: tool calls go through policy
evaluation and audit recording, LLM calls are budget-tracked, and the
full conversation is captured in an ExecutionTrace.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from agenticapi.exceptions import PolicyViolation, ToolError
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt, LLMResponse

if TYPE_CHECKING:
    from agenticapi.harness.engine import HarnessEngine
    from agenticapi.harness.policy.budget_policy import BudgetPolicy
    from agenticapi.harness.policy.pricing import PricingRegistry
    from agenticapi.interface.stream import AgentStream
    from agenticapi.runtime.context import AgentContext
    from agenticapi.runtime.llm.base import LLMBackend
    from agenticapi.runtime.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class LoopConfig:
    """Configuration for the multi-turn agentic loop.

    Attributes:
        max_iterations: Maximum number of LLM round-trips before
            the loop terminates and returns the last response.
        stop_on_no_tool_calls: If ``True`` (default), the loop stops
            when the LLM returns no tool calls even if
            ``finish_reason`` is not ``"stop"``.
    """

    max_iterations: int = 10
    stop_on_no_tool_calls: bool = True


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """Record of one tool call within the agentic loop.

    Attributes:
        iteration: The loop iteration (1-based) in which this
            tool call was dispatched.
        tool_name: Name of the tool that was invoked.
        arguments: The arguments passed to the tool.
        result: The return value from the tool invocation.
        duration_ms: Wall-clock time for the tool call in
            milliseconds.
    """

    iteration: int
    tool_name: str
    arguments: dict[str, Any]
    result: Any
    duration_ms: float


@dataclass(slots=True)
class LoopResult:
    """Result of a completed agentic loop.

    Attributes:
        final_text: The LLM's final text response after all tool
            calls have been processed.
        iterations: Number of LLM round-trips completed.
        tool_calls_made: Ordered list of every tool call dispatched
            during the loop.
        total_input_tokens: Cumulative input tokens across all LLM
            calls.
        total_output_tokens: Cumulative output tokens across all LLM
            calls.
        total_cost_usd: Cumulative estimated cost in USD (requires
            ``budget_policy``).
        conversation: The full conversation history including
            tool results.
    """

    final_text: str
    iterations: int
    tool_calls_made: list[ToolCallRecord]
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    conversation: list[LLMMessage]


def _tools_to_llm_format(tools: ToolRegistry) -> list[dict[str, Any]]:
    """Convert tool definitions to the LLM prompt format."""
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.parameters_schema,
        }
        for definition in tools.get_definitions()
    ]


def _serialize_tool_result(result: Any) -> str:
    """Serialize a tool result to a string for the LLM conversation."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError):
        return str(result)


async def run_agentic_loop(
    *,
    llm: LLMBackend,
    tools: ToolRegistry,
    harness: HarnessEngine | None = None,
    prompt: LLMPrompt,
    config: LoopConfig | None = None,
    budget_policy: BudgetPolicy | None = None,
    pricing: PricingRegistry | None = None,
    context: AgentContext | None = None,
) -> LoopResult:
    """Execute the multi-turn agentic loop.

    The loop implements the ReAct (Reason + Act) pattern:

    1. Send the prompt (with tool definitions) to the LLM.
    2. If the LLM returns ``tool_calls``: dispatch each tool call
       through the harness (policy check, audit, observability).
    3. Append tool results as messages to the conversation.
    4. Send the updated conversation back to the LLM.
    5. Repeat until the LLM returns ``finish_reason="stop"`` or
       the ``max_iterations`` limit is reached.

    Args:
        llm: The LLM backend to use for generation.
        tools: The tool registry containing available tools.
        harness: Optional harness engine for policy-checked tool
            dispatch. When ``None``, tools are invoked directly.
        prompt: The initial LLM prompt. ``prompt.tools`` is
            overridden with definitions from ``tools``.
        config: Loop configuration. Defaults to ``LoopConfig()``.
        budget_policy: Optional budget policy for cost tracking.
            Each LLM call is checked against the budget.
        pricing: Optional pricing registry for cost estimation.
            Required when ``budget_policy`` is set.
        context: Optional agent context for tracing and audit.

    Returns:
        A ``LoopResult`` with the final text, iteration count,
        all tool call records, and token/cost totals.

    Raises:
        BudgetExceeded: If a budget ceiling is breached.
        PolicyViolation: If a policy denies a tool call.
        ToolError: If a tool invocation fails.
    """
    if config is None:
        config = LoopConfig()

    tool_defs = _tools_to_llm_format(tools)

    # Build the initial prompt with tool definitions injected.
    current_messages = list(prompt.messages)
    system = prompt.system

    tool_calls_made: list[ToolCallRecord] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost_usd = 0.0
    final_text = ""
    last_response_content = ""

    for iteration in range(1, config.max_iterations + 1):
        iter_prompt = LLMPrompt(
            system=system,
            messages=current_messages,
            tools=tool_defs if tool_defs else None,
            max_tokens=prompt.max_tokens,
            temperature=prompt.temperature,
            tool_choice=prompt.tool_choice,
        )

        # Budget pre-check.
        if budget_policy is not None and pricing is not None:
            from agenticapi.harness.policy.budget_policy import BudgetEvaluationContext as BudgetCtx

            budget_ctx = BudgetCtx(
                endpoint_name=context.endpoint_name if context else "",
                session_id=context.session_id if context else None,
                user_id=context.user_id if context else None,
                model=llm.model_name,
                input_tokens=sum(len(m.content) // 4 for m in current_messages),
                max_output_tokens=prompt.max_tokens,
            )
            estimate = budget_policy.estimate_and_enforce(budget_ctx)
            total_cost_usd += estimate.estimated_cost_usd

        # LLM call.
        response: LLMResponse = await llm.generate(iter_prompt)

        # Accumulate token usage.
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Budget post-reconciliation.
        if budget_policy is not None and pricing is not None:
            actual_cost = budget_policy.record_actual(
                budget_ctx,
                actual_input_tokens=response.usage.input_tokens,
                actual_output_tokens=response.usage.output_tokens,
            )
            # Replace estimate with actual for the last iteration.
            total_cost_usd = total_cost_usd - estimate.estimated_cost_usd + actual_cost

        last_response_content = response.content

        logger.info(
            "agentic_loop_iteration",
            iteration=iteration,
            finish_reason=response.finish_reason,
            tool_calls_count=len(response.tool_calls),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        # Check for stop conditions.
        response_tool_calls = list(response.tool_calls)
        if not response_tool_calls:
            # No tool calls — the LLM produced a final text answer.
            final_text = response.content
            return LoopResult(
                final_text=final_text,
                iterations=iteration,
                tool_calls_made=tool_calls_made,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                total_cost_usd=total_cost_usd,
                conversation=current_messages,
            )

        if response.finish_reason == "stop" and config.stop_on_no_tool_calls:
            final_text = response.content
            return LoopResult(
                final_text=final_text,
                iterations=iteration,
                tool_calls_made=tool_calls_made,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                total_cost_usd=total_cost_usd,
                conversation=current_messages,
            )

        # Append the assistant message with tool calls to the
        # conversation.  Include the tool_calls list so that
        # backends can reconstruct provider-native multi-turn
        # conversation formats (Anthropic tool_use blocks, OpenAI
        # tool_calls array, Gemini function_call parts).
        current_messages.append(
            LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=list(response_tool_calls),
            )
        )

        # Dispatch each tool call.
        for call in response_tool_calls:
            try:
                tool_obj = tools.get(call.name)
            except ToolError:
                logger.warning(
                    "agentic_loop_unknown_tool",
                    iteration=iteration,
                    tool=call.name,
                )
                # Append an error result so the LLM can recover.
                current_messages.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps({"error": f"Unknown tool: {call.name}"}),
                        tool_call_id=call.id,
                    )
                )
                continue

            t0 = time.monotonic()
            try:
                if harness is not None:
                    exec_result = await harness.call_tool(
                        tool=tool_obj,
                        arguments=dict(call.arguments),
                        intent_raw=context.metadata.get("intent_raw", "") if context else "",
                        intent_action=context.metadata.get("intent_action", "") if context else "",
                        intent_domain=context.metadata.get("intent_domain", "") if context else "",
                        endpoint_name=context.endpoint_name if context else "",
                        context=context,
                    )
                    tool_result = exec_result.output
                else:
                    tool_result = await tool_obj.invoke(**call.arguments)
            except PolicyViolation:
                raise
            except Exception as exc:
                logger.error(
                    "agentic_loop_tool_error",
                    iteration=iteration,
                    tool=call.name,
                    error=str(exc),
                )
                raise ToolError(f"Tool '{call.name}' failed: {exc}") from exc
            duration_ms = (time.monotonic() - t0) * 1000

            record = ToolCallRecord(
                iteration=iteration,
                tool_name=call.name,
                arguments=dict(call.arguments),
                result=tool_result,
                duration_ms=round(duration_ms, 2),
            )
            tool_calls_made.append(record)

            # Append the tool result to the conversation with
            # tool_call_id linking it to the originating call.
            current_messages.append(
                LLMMessage(
                    role="tool",
                    content=_serialize_tool_result(tool_result),
                    tool_call_id=call.id,
                )
            )

            logger.info(
                "agentic_loop_tool_dispatched",
                iteration=iteration,
                tool=call.name,
                duration_ms=round(duration_ms, 2),
            )

    # Max iterations reached — return the last text we have.
    final_text = final_text or last_response_content
    return LoopResult(
        final_text=final_text,
        iterations=config.max_iterations,
        tool_calls_made=tool_calls_made,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_cost_usd=total_cost_usd,
        conversation=current_messages,
    )


async def run_agentic_loop_streaming(
    *,
    llm: LLMBackend,
    tools: ToolRegistry,
    harness: HarnessEngine | None = None,
    prompt: LLMPrompt,
    config: LoopConfig | None = None,
    context: AgentContext | None = None,
    stream: AgentStream,
) -> LoopResult:
    """Execute the agentic loop while emitting streaming events.

    Same logic as :func:`run_agentic_loop` but yields typed
    :class:`AgentEvent` objects through the ``stream`` for real-time
    visibility into the loop's progress.

    Events emitted per iteration:

    - :class:`ToolCallStartedEvent` — before each tool dispatch
    - :class:`ToolResultEvent` — after each tool completes
    - :class:`ThoughtEvent` — when the LLM produces reasoning text
      alongside tool calls
    - :class:`FinalEvent` — when the loop ends with a final answer

    Args:
        llm: The LLM backend.
        tools: Available tools.
        harness: Optional harness for governed tool dispatch.
        prompt: Initial prompt.
        config: Loop configuration.
        context: Agent context.
        stream: The :class:`AgentStream` to emit events on.

    Returns:
        A :class:`LoopResult` with full execution details.
    """
    if config is None:
        config = LoopConfig()

    tool_defs = _tools_to_llm_format(tools)
    current_messages = list(prompt.messages)
    system = prompt.system

    tool_calls_made: list[ToolCallRecord] = []
    total_input_tokens = 0
    total_output_tokens = 0
    final_text = ""
    last_response_content = ""

    for iteration in range(1, config.max_iterations + 1):
        iter_prompt = LLMPrompt(
            system=system,
            messages=current_messages,
            tools=tool_defs if tool_defs else None,
            max_tokens=prompt.max_tokens,
            temperature=prompt.temperature,
            tool_choice=prompt.tool_choice,
        )

        response: LLMResponse = await llm.generate(iter_prompt)
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        last_response_content = response.content

        response_tool_calls = list(response.tool_calls)

        # Emit a thought if the LLM produced text alongside tool calls.
        if response.content and response_tool_calls:
            await stream.emit_thought(response.content)

        if not response_tool_calls:
            final_text = response.content
            await stream.emit_final(result=final_text)
            return LoopResult(
                final_text=final_text,
                iterations=iteration,
                tool_calls_made=tool_calls_made,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                total_cost_usd=0.0,
                conversation=current_messages,
            )

        current_messages.append(
            LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=list(response_tool_calls),
            )
        )

        for call in response_tool_calls:
            await stream.emit_tool_call_started(
                call_id=call.id,
                name=call.name,
                arguments=dict(call.arguments),
            )

            try:
                tool_obj = tools.get(call.name)
            except ToolError:
                await stream.emit_tool_call_completed(
                    call_id=call.id,
                    is_error=True,
                    result_summary=f"Unknown tool: {call.name}",
                )
                current_messages.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps({"error": f"Unknown tool: {call.name}"}),
                        tool_call_id=call.id,
                    )
                )
                continue

            t0 = time.monotonic()
            try:
                if harness is not None:
                    exec_result = await harness.call_tool(
                        tool=tool_obj,
                        arguments=dict(call.arguments),
                        intent_raw=context.metadata.get("intent_raw", "") if context else "",
                        intent_action=context.metadata.get("intent_action", "") if context else "",
                        intent_domain=context.metadata.get("intent_domain", "") if context else "",
                        endpoint_name=context.endpoint_name if context else "",
                        context=context,
                    )
                    tool_result = exec_result.output
                else:
                    tool_result = await tool_obj.invoke(**call.arguments)
            except PolicyViolation:
                raise
            except Exception as exc:
                raise ToolError(f"Tool '{call.name}' failed: {exc}") from exc
            duration_ms = (time.monotonic() - t0) * 1000

            record = ToolCallRecord(
                iteration=iteration,
                tool_name=call.name,
                arguments=dict(call.arguments),
                result=tool_result,
                duration_ms=round(duration_ms, 2),
            )
            tool_calls_made.append(record)

            await stream.emit_tool_call_completed(
                call_id=call.id,
                result_summary=_serialize_tool_result(tool_result)[:200],
                duration_ms=round(duration_ms, 2),
            )
            await stream.emit_tool_result(
                tool_name=call.name,
                result=tool_result,
                duration_ms=round(duration_ms, 2),
                iteration=iteration,
            )

            current_messages.append(
                LLMMessage(
                    role="tool",
                    content=_serialize_tool_result(tool_result),
                    tool_call_id=call.id,
                )
            )

    final_text = final_text or last_response_content
    await stream.emit_final(result=final_text)
    return LoopResult(
        final_text=final_text,
        iterations=config.max_iterations,
        tool_calls_made=tool_calls_made,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_cost_usd=0.0,
        conversation=current_messages,
    )
