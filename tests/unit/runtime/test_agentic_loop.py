"""Tests for the multi-turn agentic loop."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import ToolError
from agenticapi.runtime.context import AgentContext
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt, ToolCall
from agenticapi.runtime.llm.mock import MockBackend
from agenticapi.runtime.loop import LoopConfig, LoopResult, run_agentic_loop, run_agentic_loop_streaming
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition
from agenticapi.runtime.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeTool:
    """Minimal tool that satisfies the Tool protocol."""

    def __init__(self, name: str, result: object = "ok") -> None:
        self._definition = ToolDefinition(
            name=name,
            description=f"Test tool {name}",
            capabilities=[ToolCapability.READ],
            parameters_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        )
        self._result = result

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def invoke(self, **kwargs: object) -> object:
        return self._result


class _FailingTool:
    """Tool that raises on invoke."""

    def __init__(self, name: str = "failing") -> None:
        self._definition = ToolDefinition(
            name=name,
            description="Always fails",
            capabilities=[ToolCapability.EXECUTE],
            parameters_schema={"type": "object", "properties": {}},
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def invoke(self, **kwargs: object) -> object:
        raise RuntimeError("boom")


def _make_prompt(msg: str = "test") -> LLMPrompt:
    return LLMPrompt(
        system="You are a helpful agent.",
        messages=[LLMMessage(role="user", content=msg)],
    )


def _make_registry(*tools: object) -> ToolRegistry:
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)  # type: ignore[arg-type]
    return registry


def _make_context() -> AgentContext:
    return AgentContext(
        trace_id="test-trace-id",
        endpoint_name="test-endpoint",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgenticLoopHappyPath:
    """Two-iteration loop: tool call on iter 1, final text on iter 2."""

    async def test_basic_two_iteration_loop(self) -> None:
        backend = MockBackend()
        # Iteration 1: LLM returns a tool call.
        backend.add_tool_call_response(ToolCall(id="c1", name="search", arguments={"q": "hello"}))
        # Iteration 2: LLM returns final text.
        backend.add_response("The answer is 42.")

        registry = _make_registry(_FakeTool("search", result={"answer": 42}))

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt("What is the answer?"),
        )

        assert isinstance(result, LoopResult)
        assert result.iterations == 2
        assert result.final_text == "The answer is 42."
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0].tool_name == "search"
        assert result.tool_calls_made[0].arguments == {"q": "hello"}
        assert result.tool_calls_made[0].result == {"answer": 42}
        assert result.tool_calls_made[0].iteration == 1
        assert result.tool_calls_made[0].duration_ms >= 0

    async def test_no_tool_calls_returns_immediately(self) -> None:
        """LLM returns text on the first call — 0 tool calls, 1 iteration."""
        backend = MockBackend(responses=["Direct answer."])
        registry = _make_registry(_FakeTool("unused"))

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt(),
        )

        assert result.iterations == 1
        assert result.final_text == "Direct answer."
        assert result.tool_calls_made == []


class TestAgenticLoopMultiTool:
    """LLM returns multiple tool calls in a single iteration."""

    async def test_two_tools_dispatched_in_parallel(self) -> None:
        backend = MockBackend()
        # Iteration 1: LLM returns two tool calls.
        backend.add_tool_call_response(
            [
                ToolCall(id="c1", name="weather", arguments={"q": "Tokyo"}),
                ToolCall(id="c2", name="transit", arguments={"q": "Tokyo"}),
            ]
        )
        # Iteration 2: LLM returns final text.
        backend.add_response("It's sunny. Trains are running.")

        registry = _make_registry(
            _FakeTool("weather", result={"temp": 22}),
            _FakeTool("transit", result={"status": "normal"}),
        )

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt(),
        )

        assert result.iterations == 2
        assert len(result.tool_calls_made) == 2
        assert result.tool_calls_made[0].tool_name == "weather"
        assert result.tool_calls_made[1].tool_name == "transit"
        assert result.final_text == "It's sunny. Trains are running."


class TestAgenticLoopThreeIterations:
    """Three-iteration chain: tool -> tool -> final answer."""

    async def test_three_iteration_chain(self) -> None:
        backend = MockBackend()
        # Iteration 1: first tool call.
        backend.add_tool_call_response(ToolCall(id="c1", name="weather", arguments={"q": "Tokyo"}))
        # Iteration 2: second tool call based on first result.
        backend.add_tool_call_response(ToolCall(id="c2", name="advice", arguments={"q": "rain"}))
        # Iteration 3: final text.
        backend.add_response("Bring an umbrella.")

        registry = _make_registry(
            _FakeTool("weather", result={"rain_pct": 80}),
            _FakeTool("advice", result="wear waterproof"),
        )

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt("Should I go out?"),
        )

        assert result.iterations == 3
        assert len(result.tool_calls_made) == 2
        assert result.tool_calls_made[0].tool_name == "weather"
        assert result.tool_calls_made[0].iteration == 1
        assert result.tool_calls_made[1].tool_name == "advice"
        assert result.tool_calls_made[1].iteration == 2
        assert result.final_text == "Bring an umbrella."


class TestAgenticLoopMaxIterations:
    """Loop stops at max_iterations even if LLM keeps returning tool calls."""

    async def test_max_iterations_enforced(self) -> None:
        backend = MockBackend()
        # Queue 5 tool call responses — but max_iterations=3.
        for i in range(5):
            backend.add_tool_call_response(ToolCall(id=f"c{i}", name="search", arguments={"q": str(i)}))

        registry = _make_registry(_FakeTool("search", result="found"))

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt(),
            config=LoopConfig(max_iterations=3),
        )

        assert result.iterations == 3
        assert len(result.tool_calls_made) == 3


class TestAgenticLoopWithHarness:
    """Tool calls are dispatched through HarnessEngine.call_tool()."""

    async def test_harness_call_tool_invoked(self) -> None:
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="search", arguments={"q": "test"}))
        backend.add_response("Done.")

        registry = _make_registry(_FakeTool("search", result="harness_result"))

        # Use a real HarnessEngine with no policies for a lightweight test.
        from agenticapi.harness.engine import HarnessEngine

        harness = HarnessEngine()
        ctx = _make_context()

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            harness=harness,
            prompt=_make_prompt(),
            context=ctx,
        )

        assert result.iterations == 2
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0].result == "harness_result"


class TestAgenticLoopUnknownTool:
    """Unknown tool name results in an error message sent back to LLM."""

    async def test_unknown_tool_sends_error_to_llm(self) -> None:
        backend = MockBackend()
        # LLM asks for a tool that doesn't exist.
        backend.add_tool_call_response(ToolCall(id="c1", name="nonexistent", arguments={}))
        # LLM recovers after seeing the error.
        backend.add_response("I couldn't find that tool.")

        registry = _make_registry(_FakeTool("search"))

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt(),
        )

        assert result.iterations == 2
        assert result.tool_calls_made == []  # No successful tool calls
        assert result.final_text == "I couldn't find that tool."


class TestAgenticLoopToolError:
    """Tool invocation failure raises ToolError."""

    async def test_tool_failure_raises(self) -> None:
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="failing", arguments={}))

        registry = _make_registry(_FailingTool("failing"))

        with pytest.raises(ToolError, match="Tool 'failing' failed"):
            await run_agentic_loop(
                llm=backend,
                tools=registry,
                prompt=_make_prompt(),
            )


class TestAgenticLoopConversationHistory:
    """Verify the conversation history is built correctly."""

    async def test_conversation_includes_tool_results(self) -> None:
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="lookup", arguments={"q": "data"}))
        backend.add_response("Here is the data.")

        registry = _make_registry(_FakeTool("lookup", result={"key": "value"}))

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt("Get data"),
        )

        # Conversation should have: user, assistant (tool call), tool result
        assert len(result.conversation) >= 3
        # Find the tool message.
        tool_msgs = [m for m in result.conversation if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert '"key"' in tool_msgs[0].content
        assert '"value"' in tool_msgs[0].content

    async def test_conversation_messages_linked_by_tool_call_id(self) -> None:
        """Assistant messages carry tool_calls; tool messages carry tool_call_id."""
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="call_42", name="lookup", arguments={"q": "x"}))
        backend.add_response("Done.")

        registry = _make_registry(_FakeTool("lookup", result="ok"))

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt("link test"),
        )

        # The assistant message should have tool_calls populated.
        assistant_msgs = [m for m in result.conversation if m.role == "assistant" and m.tool_calls]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].tool_calls[0].id == "call_42"
        assert assistant_msgs[0].tool_calls[0].name == "lookup"

        # The tool result message should have tool_call_id linking back.
        tool_msgs = [m for m in result.conversation if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_call_id == "call_42"

    async def test_unknown_tool_message_has_tool_call_id(self) -> None:
        """Even error messages for unknown tools carry the tool_call_id."""
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="call_99", name="nonexistent", arguments={}))
        backend.add_response("Sorry.")

        registry = _make_registry(_FakeTool("other"))

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt("unknown test"),
        )

        tool_msgs = [m for m in result.conversation if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_call_id == "call_99"


class TestAgenticLoopTokenAccumulation:
    """Verify token counts are accumulated across iterations."""

    async def test_tokens_accumulated(self) -> None:
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="search", arguments={"q": "x"}))
        backend.add_response("Done.")

        registry = _make_registry(_FakeTool("search"))

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt(),
        )

        # MockBackend produces non-zero usage.
        assert result.total_input_tokens > 0
        assert result.total_output_tokens > 0
        assert result.iterations == 2


class TestAgenticLoopBudgetExhaustion:
    """Budget policy triggers BudgetExceeded during the loop."""

    async def test_budget_tracked_across_iterations(self) -> None:
        """Verify budget tracking works across iterations."""
        from agenticapi.harness.policy.budget_policy import BudgetPolicy
        from agenticapi.harness.policy.pricing import PricingRegistry

        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="search", arguments={"q": "x"}))
        backend.add_response("Done.")

        registry = _make_registry(_FakeTool("search"))

        pricing = PricingRegistry.default()
        budget = BudgetPolicy(
            pricing=pricing,
            max_per_request_usd=10.0,  # High enough to not trigger
        )

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            prompt=_make_prompt(),
            budget_policy=budget,
            pricing=pricing,
            context=_make_context(),
        )

        assert result.iterations == 2
        assert len(result.tool_calls_made) == 1


class TestAgenticLoopPolicyDenial:
    """Tool call with harness policy integration."""

    async def test_harness_with_code_policy_passes_tool_calls(self) -> None:
        """Verify tool calls pass through CodePolicy (which only checks code)."""
        from agenticapi.harness.engine import HarnessEngine
        from agenticapi.harness.policy.code_policy import CodePolicy

        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="c1", name="search", arguments={"q": "test"}))
        backend.add_response("Done.")

        registry = _make_registry(_FakeTool("search"))

        harness = HarnessEngine(policies=[CodePolicy()])
        ctx = _make_context()

        result = await run_agentic_loop(
            llm=backend,
            tools=registry,
            harness=harness,
            prompt=_make_prompt(),
            context=ctx,
        )
        assert result.iterations == 2
        assert len(result.tool_calls_made) == 1


class TestLoopConfigDefaults:
    """Verify LoopConfig defaults."""

    def test_defaults(self) -> None:
        config = LoopConfig()
        assert config.max_iterations == 10
        assert config.stop_on_no_tool_calls is True

    def test_custom_values(self) -> None:
        config = LoopConfig(max_iterations=5, stop_on_no_tool_calls=False)
        assert config.max_iterations == 5
        assert config.stop_on_no_tool_calls is False


# ---------------------------------------------------------------------------
# Streaming variant
# ---------------------------------------------------------------------------


class _StubStream:
    """Minimal AgentStream stub for testing the streaming loop."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def emit_thought(self, text: str, **kw: object) -> None:
        self.events.append(("thought", {"text": text, **kw}))

    async def emit_tool_call_started(self, *, call_id: str, name: str, arguments: dict[str, object]) -> None:
        self.events.append(("tool_call_started", {"call_id": call_id, "name": name}))

    async def emit_tool_call_completed(self, *, call_id: str, **kw: object) -> None:
        self.events.append(("tool_call_completed", {"call_id": call_id, **kw}))

    async def emit_tool_result(self, **kw: object) -> None:
        self.events.append(("tool_result", kw))

    async def emit_final(self, *, result: object) -> None:
        self.events.append(("final", {"result": result}))


class TestAgenticLoopStreamingConversation:
    """Verify streaming loop sets tool_call_id and tool_calls on messages."""

    async def test_streaming_messages_linked_by_tool_call_id(self) -> None:
        backend = MockBackend()
        backend.add_tool_call_response(ToolCall(id="sc1", name="search", arguments={"q": "hi"}))
        backend.add_response("Done.")

        registry = _make_registry(_FakeTool("search"))
        stream = _StubStream()

        result = await run_agentic_loop_streaming(
            llm=backend,
            tools=registry,
            prompt=_make_prompt("streaming test"),
            stream=stream,  # type: ignore[arg-type]
        )

        # Assistant message should have tool_calls.
        assistant_msgs = [m for m in result.conversation if m.role == "assistant" and m.tool_calls]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].tool_calls[0].id == "sc1"
        assert assistant_msgs[0].tool_calls[0].name == "search"

        # Tool result message should have tool_call_id.
        tool_msgs = [m for m in result.conversation if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].tool_call_id == "sc1"

        # Stream should have emitted the right events.
        event_types = [e[0] for e in stream.events]
        assert "tool_call_started" in event_types
        assert "tool_call_completed" in event_types
        assert "final" in event_types
