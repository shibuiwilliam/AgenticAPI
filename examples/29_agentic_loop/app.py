"""Agentic Loop example: a weather advisor that reasons over multiple tools.

Demonstrates AgenticAPI's **multi-turn agentic loop** — the framework's
built-in ReAct pattern where the LLM autonomously decides which tools
to call, inspects intermediate results, and reasons to a final answer.

This is the defining feature of an AI agent: the developer registers
tools, the LLM decides the execution plan, and the harness governs
every step (policy checks, audit, budget tracking).

Features demonstrated:

- **Three ``@tool``-decorated tools** — ``get_weather``,
  ``get_clothing_advice``, and ``get_transit_status``.
- **Autonomous tool selection** — the LLM decides which tools to call
  and in what order based on the user's question.
- **Multi-turn reasoning** — the LLM calls ``get_weather``, sees 80%
  rain, then calls ``get_clothing_advice`` with the rain data, and
  finally produces a reasoned recommendation.
- **Harness governance** — every tool call goes through
  ``HarnessEngine.call_tool()`` with policy evaluation and audit.
- **``LoopConfig``** — configurable iteration limit per endpoint.
- **``MockBackend``** with pre-queued responses so the example runs
  without any API key.

Run with::

    uvicorn examples.29_agentic_loop.app:app --reload

Test with curl::

    curl -X POST http://127.0.0.1:8000/agent/advisor \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Should I go out in Tokyo today?"}'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi import AgenticApp, tool
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.runtime.llm.base import ToolCall
from agenticapi.runtime.llm.mock import MockBackend
from agenticapi.runtime.loop import LoopConfig
from agenticapi.runtime.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# Tools — the LLM chooses which to call and when
# ---------------------------------------------------------------------------


@tool(description="Get current weather for a city")
async def get_weather(city: str) -> dict[str, Any]:
    """Return simulated weather data for the given city."""
    return {
        "city": city,
        "temp_celsius": 22,
        "rain_percent": 80,
        "wind_kph": 15,
        "condition": "cloudy with rain expected",
    }


@tool(description="Get clothing advice based on temperature and rain")
async def get_clothing_advice(temp_celsius: int, is_raining: bool) -> str:
    """Return clothing recommendation based on weather conditions."""
    if is_raining:
        return "Wear a waterproof jacket and carry an umbrella."
    if temp_celsius < 15:
        return "Wear a warm coat."
    return "Light clothing is fine."


@tool(description="Get public transit status for a city")
async def get_transit_status(city: str) -> dict[str, str]:
    """Return simulated transit status."""
    return {
        "city": city,
        "trains": "running normally",
        "buses": "minor delays on route 7",
        "metro": "all lines operational",
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

registry = ToolRegistry()
registry.register(get_weather)
registry.register(get_clothing_advice)
registry.register(get_transit_status)

# ---------------------------------------------------------------------------
# MockBackend with pre-queued multi-turn responses
# ---------------------------------------------------------------------------

backend = MockBackend()

# Intent parsing response.
backend.add_response('{"action":"read","domain":"weather","parameters":{},"confidence":0.9}')

# Agentic loop iteration 1: LLM decides to call get_weather first.
backend.add_tool_call_response(ToolCall(id="call_1", name="get_weather", arguments={"city": "Tokyo"}))

# Agentic loop iteration 2: After seeing the weather (80% rain),
# the LLM calls get_clothing_advice.
backend.add_tool_call_response(
    ToolCall(
        id="call_2",
        name="get_clothing_advice",
        arguments={"temp_celsius": 22, "is_raining": True},
    )
)

# Agentic loop iteration 3: The LLM has enough information and
# produces its final reasoned answer.
backend.add_response(
    "Based on my research:\n\n"
    "- Tokyo is 22\u00b0C with 80% chance of rain and 15 kph winds\n"
    "- You should wear a waterproof jacket and carry an umbrella\n"
    "- Trains are running normally, buses have minor delays on route 7\n\n"
    "Yes, you can go out, but dress for rain!"
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

harness = HarnessEngine(policies=[CodePolicy()])

app = AgenticApp(
    title="Weather Advisor (Agentic Loop)",
    description=(
        "A weather advisor agent that uses the multi-turn agentic loop "
        "to autonomously call tools and reason to a final answer."
    ),
    harness=harness,
    llm=backend,
    tools=registry,
)


@app.agent_endpoint(
    name="advisor",
    description="Ask about weather and get actionable advice",
    autonomy_level="auto",
    loop_config=LoopConfig(max_iterations=5),
)
async def advisor(intent: Any, context: AgentContext) -> dict[str, Any]:
    """Weather advisor endpoint.

    The handler itself doesn't need to do anything — the agentic loop
    handles tool dispatch and LLM reasoning automatically. This handler
    is a fallback for direct-handler mode (when no LLM is configured).
    """
    return {"message": "No LLM configured — use the agentic loop path."}
