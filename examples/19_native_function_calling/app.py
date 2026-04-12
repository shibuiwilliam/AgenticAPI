"""Native Function Calling example: a travel concierge with tool use.

Demonstrates AgenticAPI's support for **native LLM function calling**
— the production pattern where modern LLM APIs (Anthropic ``tools``,
OpenAI function calling, Gemini ``function_declarations``) emit
structured :class:`ToolCall` objects instead of generating Python
code for the sandbox to run. The framework captures these in
``LLMResponse.tool_calls``; this example shows the remaining twenty
lines of glue: prompt construction, tool dispatch, and the
multi-turn reasoning loop.

Why a dedicated example?
    All of AgenticAPI's *other* tool-flavoured examples hit a
    different code path:

    * Example 02 (ecommerce) — LLM writes Python that the harness
      sandboxes and runs. Powerful, but a full harness stage per
      call.
    * Example 14 (dependency injection) — ``@tool`` plus static
      dispatch inside a DI-resolved handler, no LLM in the loop.
    * Example 17 (typed intents) — schema-constrained *single*
      structured output, no tools.

    This example fills the remaining gap: **dynamic dispatch of
    structured tool calls the model itself selects**, which is the
    2026 production path. It is faster, cheaper, and more reliable
    than code generation because the provider APIs are optimised for
    it.

Features demonstrated:

- **Four ``@tool``-decorated tools** — ``get_weather``,
  ``search_flights``, ``check_hotel_availability``, and
  ``calculate_budget``. Each has a Pydantic-derived JSON schema that
  the framework forwards to the LLM.
- **``ToolRegistry`` as the dispatch table** —
  ``registry.get(name).invoke(**arguments)`` is the one-line
  dispatch.
- **Prompt wiring** — ``LLMPrompt(tools=_tools_for_llm(registry))``
  advertises the tools to the model via the provider-agnostic
  OpenAI-style shape the backends all accept.
- **Single-turn dispatch** at ``POST /agent/travel.plan`` — the
  model returns one ``ToolCall``, the handler dispatches it via the
  registry, and the result is returned alongside ``finish_reason``.
- **Multi-turn tool-use loop** at ``POST /agent/travel.chat`` —
  iterate until the model stops calling tools, appending every tool
  result to the conversation as the next turn's context.
- **Tool catalogue** at ``POST /agent/travel.tools`` — no LLM call;
  enumerate the registry for clients that want to introspect the
  available tools and their schemas without reading OpenAPI.
- **``finish_reason`` branching** — the loop inspects
  ``"tool_calls"`` vs ``"stop"`` to decide whether to iterate or
  return the model's final answer.
- **Deterministic ``MockBackend``** —
  :meth:`MockBackend.add_tool_call_response` queues provider-native
  tool calls so the demo and its tests run without any API key while
  exercising the *exact* same code path a real provider would
  trigger. Swapping in ``AnthropicBackend``, ``OpenAIBackend``, or
  ``GeminiBackend`` is a two-line change.

Run with::

    uvicorn examples.19_native_function_calling.app:app --reload

Test with curl (run in order — the mock queue is consumed FIFO)::

    # 1. Inspect the tool catalogue (no LLM call, no queue consumption)
    curl -X POST http://127.0.0.1:8000/agent/travel.tools \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "what can you do?"}'

    # 2. Single-turn: the model picks ``get_weather``, handler dispatches
    curl -X POST http://127.0.0.1:8000/agent/travel.plan \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "What is the weather in Tokyo?"}'

    # 3. Multi-turn: search flights -> check hotels -> final answer
    curl -X POST http://127.0.0.1:8000/agent/travel.chat \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Plan a three-night trip to Paris for next Friday"}'
"""

from __future__ import annotations

from typing import Any

from agenticapi import AgenticApp, Intent, tool
from agenticapi.routing import AgentRouter
from agenticapi.runtime.context import AgentContext  # noqa: TC001 — runtime import needed
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt, ToolCall
from agenticapi.runtime.llm.mock import MockBackend
from agenticapi.runtime.tools import ToolRegistry

# ---------------------------------------------------------------------------
# 1. Tools — plain functions turned into registered tools by @tool
# ---------------------------------------------------------------------------
#
# Each tool is an ordinary Python function with a docstring and typed
# parameters. The ``@tool`` decorator:
#
#   * derives a ``ToolDefinition`` (name, description, capabilities),
#   * builds a Pydantic-driven JSON schema from the signature, and
#   * keeps the function directly callable from Python so tests and
#     other handlers can invoke it without the registry indirection.


@tool(description="Get the current weather for a city.")
def get_weather(city: str) -> dict[str, Any]:
    """Return mock weather for the given city.

    A real implementation would call a weather provider. The static
    payload here keeps the demo deterministic and dependency-free.
    """
    return {
        "city": city,
        "temperature_c": 22,
        "conditions": "sunny",
        "humidity_pct": 55,
    }


@tool(description="Search for flights between two cities on a given date.")
def search_flights(origin: str, destination: str, date: str) -> list[dict[str, Any]]:
    """Return a deterministic list of two mock flights."""
    return [
        {
            "airline": "Air Mock",
            "origin": origin,
            "destination": destination,
            "depart": f"{date} 08:00",
            "arrive": f"{date} 19:00",
            "price_usd": 340,
            "stops": 0,
        },
        {
            "airline": "Demo Airways",
            "origin": origin,
            "destination": destination,
            "depart": f"{date} 14:30",
            "arrive": f"{date} 22:45",
            "price_usd": 280,
            "stops": 1,
        },
    ]


@tool(description="Check hotel availability in a city for the given stay.")
def check_hotel_availability(
    city: str,
    check_in: str,
    nights: int,
) -> list[dict[str, Any]]:
    """Return two mock hotel options for the requested stay."""
    return [
        {
            "name": "Central Hotel",
            "city": city,
            "check_in": check_in,
            "nights": nights,
            "price_per_night_usd": 150,
            "rating": 4.2,
        },
        {
            "name": "Budget Inn",
            "city": city,
            "check_in": check_in,
            "nights": nights,
            "price_per_night_usd": 80,
            "rating": 3.5,
        },
    ]


@tool(description="Sum a list of items with a cost_usd field and return the total.")
def calculate_budget(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the total USD cost and item count from a list of items."""
    total = sum(float(item.get("cost_usd", 0)) for item in items)
    return {"total_usd": total, "item_count": len(items)}


# ---------------------------------------------------------------------------
# 2. Registry — the dispatch table
# ---------------------------------------------------------------------------
#
# Every ``@tool``-decorated function satisfies the ``Tool`` protocol,
# so it can be registered directly. ``registry.get(name)`` is what the
# handlers below use to resolve a ``ToolCall.name`` to an
# implementation.

registry = ToolRegistry()
registry.register(get_weather)
registry.register(search_flights)
registry.register(check_hotel_availability)
registry.register(calculate_budget)


def _tools_for_llm(reg: ToolRegistry) -> list[dict[str, Any]]:
    """Convert every registered tool into the shape
    :class:`LLMPrompt` expects in its ``tools`` field.

    The framework passes this list through to the backend, which
    translates it into the provider's native function-calling schema
    (Anthropic ``tools``, OpenAI ``tools``, Gemini
    ``function_declarations``). ``MockBackend`` only keys off
    ``prompt.tools`` being truthy to pick the tool-call branch, so
    it doesn't care about the exact shape — but real backends will
    round-trip this payload through their SDK. The OpenAI-flavoured
    wrapper below is the portable choice: every supported provider
    accepts (or trivially adapts) it.
    """
    out: list[dict[str, Any]] = []
    for definition in reg.list_tools():
        out.append(
            {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    "parameters": definition.parameters_schema,
                },
            }
        )
    return out


# ---------------------------------------------------------------------------
# 3. Mock LLM backend pre-loaded with deterministic tool calls
# ---------------------------------------------------------------------------
#
# Three scenarios are queued up front so the curl walkthrough runs
# top-to-bottom without any API keys and every call lands on the same
# code path a real provider would trigger:
#
#   * Scenario A — ``travel.plan`` consumes one ``ToolCall`` for
#     ``get_weather(city="Tokyo")``.
#
#   * Scenario B — ``travel.chat`` runs the multi-turn loop: two
#     ``ToolCall`` responses (flights and hotels) followed by a plain
#     text response that tells the loop to stop iterating.
#
# When ``prompt.tools`` is set *and* the tool-call queue is non-empty,
# ``MockBackend`` pops a tool-call bundle and returns it with
# ``finish_reason="tool_calls"``. When the tool-call queue drains to
# empty, subsequent tools-enabled calls fall through to the plain
# text queue, producing a response with an empty ``tool_calls`` list
# — which is the "final answer" the loop is waiting for.

mock_llm = MockBackend()

# Scenario A: single-turn plan.
mock_llm.add_tool_call_response(
    [
        ToolCall(
            id="call_weather_tokyo",
            name="get_weather",
            arguments={"city": "Tokyo"},
        )
    ]
)

# Scenario B: multi-turn chat — two tool calls, then a final text.
mock_llm.add_tool_call_response(
    [
        ToolCall(
            id="call_flights_paris",
            name="search_flights",
            arguments={
                "origin": "NYC",
                "destination": "Paris",
                "date": "2026-04-17",
            },
        )
    ]
)
mock_llm.add_tool_call_response(
    [
        ToolCall(
            id="call_hotels_paris",
            name="check_hotel_availability",
            arguments={
                "city": "Paris",
                "check_in": "2026-04-17",
                "nights": 3,
            },
        )
    ]
)
mock_llm.add_response(
    "Your three-night Paris trip is booked. Demo Airways at 14:30 "
    "for $280, Central Hotel for three nights at $150/night ($450). "
    "Have a great trip!"
)


# ---------------------------------------------------------------------------
# 4. App + endpoints
# ---------------------------------------------------------------------------
#
# Note the deliberate omission of ``llm=mock_llm`` on ``AgenticApp``.
# The framework's intent parser would happily reach for it before any
# handler ran and consume text responses from the queue — but this
# example's handlers drive the mock LLM *directly* because the whole
# point is to exercise the native-function-calling path explicitly.
# Letting the framework route intents through keyword fallback keeps
# the mock queue fully under the handlers' control, which in turn
# makes the FIFO ordering of queued tool calls predictable for both
# the curl walkthrough and the e2e tests.

app = AgenticApp(
    title="Travel Concierge (Native Function Calling demo)",
    version="0.1.0",
)

travel = AgentRouter(prefix="travel", tags=["travel"])

#: Hard cap on the tool-use loop so a pathological model cannot spin
#: forever. Six iterations is enough for every realistic plan-then-
#: refine scenario while still catching runaway cases quickly.
MAX_TOOL_TURNS = 6


@travel.agent_endpoint(
    name="tools",
    description="List every registered tool with its JSON schema.",
    autonomy_level="auto",
)
async def list_tools(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Enumerate registry contents without calling the LLM.

    Useful as a cheap "what can you do?" introspection endpoint and
    as a smoke test for the registry wiring.
    """
    definitions = registry.list_tools()
    return {
        "count": len(definitions),
        "tools": [
            {
                "name": d.name,
                "description": d.description,
                "capabilities": [c.value for c in d.capabilities],
                "parameters_schema": d.parameters_schema,
            }
            for d in definitions
        ],
    }


@travel.agent_endpoint(
    name="plan",
    description="Single-turn tool dispatch: the model picks one tool, the handler dispatches it.",
    autonomy_level="auto",
)
async def travel_plan(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Single-turn native function calling.

    The model is asked to answer the user's request with access to
    the registered tools. When it returns
    ``finish_reason == "tool_calls"`` the handler dispatches every
    requested call via the registry and returns the results
    alongside the raw intent. When the model answers with plain text
    instead, the handler returns that text and an empty dispatch
    list.
    """
    prompt = LLMPrompt(
        system=(
            "You are a concise travel assistant. You have access to tools "
            "for weather, flights, hotels, and budget calculation. Prefer "
            "calling a tool over guessing."
        ),
        messages=[LLMMessage(role="user", content=intent.raw)],
        tools=_tools_for_llm(registry),
    )
    response = await mock_llm.generate(prompt)

    if response.finish_reason == "tool_calls":
        dispatches: list[dict[str, Any]] = []
        for call in response.tool_calls:
            impl = registry.get(call.name)
            result = await impl.invoke(**call.arguments)
            dispatches.append(
                {
                    "call_id": call.id,
                    "tool": call.name,
                    "arguments": call.arguments,
                    "result": result,
                }
            )
        return {
            "finish_reason": response.finish_reason,
            "turns_taken": 1,
            "dispatched_tools": dispatches,
            "answer": None,
            "raw_intent": intent.raw,
        }

    return {
        "finish_reason": response.finish_reason,
        "turns_taken": 1,
        "dispatched_tools": [],
        "answer": response.content,
        "raw_intent": intent.raw,
    }


@travel.agent_endpoint(
    name="chat",
    description="Multi-turn tool-use loop: dispatch, feed results back, iterate until the model stops.",
    autonomy_level="auto",
)
async def travel_chat(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Full multi-turn tool-use loop.

    Rather than a single call/dispatch/return cycle, this handler
    iterates:

    1. Ask the LLM with the tools advertised.
    2. If ``finish_reason == "tool_calls"``, dispatch every call,
       record the result, append a synthetic ``LLMMessage`` with the
       tool result so the next iteration can see it, and loop.
    3. Otherwise, return the model's final text answer alongside the
       full tool-call history.

    ``MAX_TOOL_TURNS`` bounds the loop so a pathological model cannot
    keep asking for tools forever.
    """
    messages: list[LLMMessage] = [LLMMessage(role="user", content=intent.raw)]
    history: list[dict[str, Any]] = []

    for turn in range(1, MAX_TOOL_TURNS + 1):
        prompt = LLMPrompt(
            system=(
                "You are a helpful travel assistant. Use tools iteratively: "
                "first find flights, then hotels, then summarise the plan. "
                "Stop calling tools once you have enough information."
            ),
            messages=messages,
            tools=_tools_for_llm(registry),
        )
        response = await mock_llm.generate(prompt)

        # Stop condition: the model produced a plain text answer.
        if response.finish_reason != "tool_calls":
            return {
                "finish_reason": response.finish_reason,
                "turns_taken": turn,
                "tool_call_history": history,
                "answer": response.content,
                "raw_intent": intent.raw,
            }

        # Dispatch every requested tool call and feed the results back
        # as user-role messages so the model can reason over them on
        # the next iteration.
        for call in response.tool_calls:
            impl = registry.get(call.name)
            result = await impl.invoke(**call.arguments)
            history.append(
                {
                    "turn": turn,
                    "call_id": call.id,
                    "tool": call.name,
                    "arguments": call.arguments,
                    "result": result,
                }
            )
            messages.append(
                LLMMessage(
                    role="user",
                    content=(f"Tool result from {call.name}: {result}. Continue planning."),
                )
            )

    # Hit the turn cap without the model stopping. Return what we
    # have so the client can see the partial progress and retry with
    # a tighter system prompt or a smaller task.
    return {
        "finish_reason": "max_turns_exceeded",
        "turns_taken": MAX_TOOL_TURNS,
        "tool_call_history": history,
        "answer": None,
        "raw_intent": intent.raw,
    }


app.include_router(travel)
