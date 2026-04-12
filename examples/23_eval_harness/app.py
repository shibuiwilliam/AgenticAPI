"""Eval Harness example: regression-test your agent endpoints.

Demonstrates AgenticAPI's **evaluation harness** (Phase C6) end-to-end.
Where pytest tests verify that *code ran*, eval sets verify that the
*behaviour met expectations*: the right answer, fast enough, under
budget, matching the schema, containing key phrases. This is the
regression gate that makes agent endpoints safe to ship in CI.

The example builds a small deterministic app (no LLM required) with
three endpoints, then evaluates those endpoints using every built-in
judge and one custom judge, both programmatically and via YAML eval
sets.

Features demonstrated
---------------------

- **EvalSet + EvalCase** — programmatic construction of a named
  regression suite with per-case expectations.
- **YAML eval sets** — loading eval cases from a YAML file via
  ``load_eval_set()``, the same format ``agenticapi eval`` consumes.
- **EvalRunner** — running a suite against a live ``AgenticApp`` and
  collecting an ``EvalReport`` with pass/fail per case.
- **Five built-in judges**:
  * ``ExactMatchJudge`` — structural equality against stored golden
    values.
  * ``ContainsJudge`` — required substring check on the JSON result.
  * ``LatencyJudge`` — wall-clock upper bound per case.
  * ``CostJudge`` — LLM cost upper bound (demonstrates no-op when
    cost is absent).
  * ``PydanticSchemaJudge`` — validate the result against a Pydantic
    model at runtime.
- **Custom judge** — implement the ``EvalJudge`` protocol in five
  lines to add domain-specific assertions.
- **``response_model=``** — Pydantic typing on every endpoint so the
  schema judge has something to validate against.
- **Self-evaluating endpoint** — ``POST /agent/eval.run`` runs the
  eval suite *against the same app*, returning the ``EvalReport``
  JSON. This is the pattern for adding a health-check-style eval
  probe to a running service.

Run
---

::

    uvicorn examples.23_eval_harness.app:app --reload
    # or
    agenticapi dev --app examples.23_eval_harness.app:app

Walkthrough with curl
---------------------

::

    # 1. Hit the deterministic endpoints the eval suite tests
    curl -s -X POST http://127.0.0.1:8000/agent/weather.forecast \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Weather in Tokyo"}'

    curl -s -X POST http://127.0.0.1:8000/agent/calc.compute \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "What is 2 + 3?"}'

    curl -s -X POST http://127.0.0.1:8000/agent/inventory.check \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Check stock for widget-A"}'

    # 2. Run the programmatic eval suite — returns the full report
    curl -s -X POST http://127.0.0.1:8000/agent/eval.run \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Run eval suite"}' | python3 -m json.tool

    # 3. Run the YAML-based eval set
    curl -s -X POST http://127.0.0.1:8000/agent/eval.run_yaml \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Run YAML eval"}' | python3 -m json.tool

    # 4. Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from agenticapi import AgenticApp
from agenticapi.evaluation import (
    ContainsJudge,
    CostJudge,
    EvalCase,
    EvalReport,
    EvalRunner,
    EvalSet,
    ExactMatchJudge,
    JudgeResult,
    LatencyJudge,
    PydanticSchemaJudge,
    load_eval_set,
)

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# 1. Pydantic response models — typed, OpenAPI-visible, schema-judge-able
# ---------------------------------------------------------------------------


class WeatherForecast(BaseModel):
    """Typed response for the weather endpoint."""

    city: str
    temperature_c: float
    condition: str
    humidity_pct: int


class CalcResult(BaseModel):
    """Typed response for the calculator endpoint."""

    expression: str
    result: float


class InventoryItem(BaseModel):
    """Typed response for the inventory endpoint."""

    sku: str
    name: str
    in_stock: bool
    quantity: int


# ---------------------------------------------------------------------------
# 2. In-memory data — deterministic so eval golden values are stable
# ---------------------------------------------------------------------------

WEATHER_DB: dict[str, dict[str, Any]] = {
    "tokyo": {"city": "Tokyo", "temperature_c": 22.5, "condition": "partly cloudy", "humidity_pct": 65},
    "london": {"city": "London", "temperature_c": 14.0, "condition": "rainy", "humidity_pct": 88},
    "new york": {"city": "New York", "temperature_c": 18.3, "condition": "sunny", "humidity_pct": 52},
}

INVENTORY_DB: dict[str, dict[str, Any]] = {
    "widget-a": {"sku": "widget-a", "name": "Widget A", "in_stock": True, "quantity": 142},
    "widget-b": {"sku": "widget-b", "name": "Widget B", "in_stock": False, "quantity": 0},
    "gadget-x": {"sku": "gadget-x", "name": "Gadget X", "in_stock": True, "quantity": 7},
}


# ---------------------------------------------------------------------------
# 3. The AgenticApp
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Eval Harness Demo",
    version="1.0.0",
    description=(
        "A small deterministic app with three endpoints, evaluated by "
        "AgenticAPI's built-in eval harness. No LLM required."
    ),
)


# ---------------------------------------------------------------------------
# 4. Deterministic endpoints — the "system under test"
# ---------------------------------------------------------------------------


@app.agent_endpoint(
    name="weather.forecast",
    description="Return a weather forecast for a city.",
    response_model=WeatherForecast,
)
async def weather_forecast(intent: Intent, context: AgentContext) -> WeatherForecast:
    """Look up a city in the weather DB and return a forecast.

    Keywords: any city name mentioned in the intent maps to a
    record. Unknown cities get a default response.
    """
    lower = intent.raw.lower()
    for city_key, data in WEATHER_DB.items():
        if city_key in lower:
            return WeatherForecast(**data)
    return WeatherForecast(city="Unknown", temperature_c=0.0, condition="unavailable", humidity_pct=0)


@app.agent_endpoint(
    name="calc.compute",
    description="Evaluate a simple arithmetic expression.",
    response_model=CalcResult,
)
async def calc_compute(intent: Intent, context: AgentContext) -> CalcResult:
    """Parse ``a + b``, ``a - b``, ``a * b``, ``a / b`` from the intent.

    Uses a tiny keyword parser so the demo runs without an LLM.
    """
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*([+\-*/])\s*(\d+(?:\.\d+)?)", intent.raw)
    if match:
        a, op, b = float(match.group(1)), match.group(2), float(match.group(3))
        result = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b != 0 else 0.0}[op]
        return CalcResult(expression=f"{a} {op} {b}", result=result)
    return CalcResult(expression=intent.raw, result=0.0)


@app.agent_endpoint(
    name="inventory.check",
    description="Check stock level for a SKU.",
    response_model=InventoryItem,
)
async def inventory_check(intent: Intent, context: AgentContext) -> InventoryItem:
    """Look up a SKU in the inventory DB."""
    lower = intent.raw.lower()
    for sku, data in INVENTORY_DB.items():
        if sku in lower:
            return InventoryItem(**data)
    return InventoryItem(sku="unknown", name="Unknown", in_stock=False, quantity=0)


# ---------------------------------------------------------------------------
# 5. Custom judge — domain-specific assertion in 5 lines
# ---------------------------------------------------------------------------


class PositiveQuantityJudge:
    """Custom judge: passes when in_stock items have quantity > 0.

    Demonstrates the ``EvalJudge`` protocol — any object with a
    ``name`` property and an ``evaluate`` method satisfying the
    protocol is a valid judge. No subclassing required.
    """

    name = "positive_quantity"

    def evaluate(
        self,
        *,
        case: EvalCase,
        live_payload: Any,
        duration_ms: float,
    ) -> JudgeResult:
        del duration_ms
        result = live_payload.get("result", live_payload) if isinstance(live_payload, dict) else live_payload
        if not isinstance(result, dict):
            return JudgeResult(name=self.name, passed=True, message="non-dict result, skipping")
        in_stock = result.get("in_stock")
        quantity = result.get("quantity")
        if in_stock is True and isinstance(quantity, (int, float)) and quantity <= 0:
            return JudgeResult(
                name=self.name,
                passed=False,
                message=f"in_stock=True but quantity={quantity}",
            )
        return JudgeResult(name=self.name, passed=True)


# ---------------------------------------------------------------------------
# 6. Programmatic eval suite
# ---------------------------------------------------------------------------


def build_programmatic_eval_set() -> EvalSet:
    """Construct an EvalSet in pure Python — no YAML needed.

    This is the shape you'd use in a pytest integration test or a
    healthcheck endpoint. The YAML form is shown separately in the
    ``eval.run_yaml`` endpoint below.

    **Important**: the same list of judges is applied to *every* case
    in a set. ``ExactMatchJudge`` compares ``case.expected`` to the
    live result; when ``expected`` is ``None`` the judge passes (there
    is nothing to compare). ``ContainsJudge`` checks ``case.contains``
    and is a no-op when the list is empty. ``LatencyJudge`` and
    ``CostJudge`` are no-ops when the per-case budget field is
    ``None``. This design lets you attach all judges once and control
    *which checks actually fire* per case via the case fields.
    """
    return EvalSet(
        name="programmatic_golden",
        cases=[
            # Weather — exact match + contains + latency
            EvalCase(
                id="weather_tokyo",
                endpoint="weather.forecast",
                intent="Weather in Tokyo",
                expected={
                    "city": "Tokyo",
                    "temperature_c": 22.5,
                    "condition": "partly cloudy",
                    "humidity_pct": 65,
                },
                contains=["Tokyo", "partly cloudy"],
                max_latency_ms=5000,
            ),
            EvalCase(
                id="weather_london",
                endpoint="weather.forecast",
                intent="What is the weather in London?",
                expected={
                    "city": "London",
                    "temperature_c": 14.0,
                    "condition": "rainy",
                    "humidity_pct": 88,
                },
                contains=["rainy"],
                max_latency_ms=5000,
            ),
            EvalCase(
                id="weather_unknown",
                endpoint="weather.forecast",
                intent="Weather in Mars",
                expected={
                    "city": "Unknown",
                    "temperature_c": 0.0,
                    "condition": "unavailable",
                    "humidity_pct": 0,
                },
                max_latency_ms=5000,
            ),
            # Calculator — exact match + latency
            EvalCase(
                id="calc_add",
                endpoint="calc.compute",
                intent="What is 2 + 3?",
                expected={"expression": "2.0 + 3.0", "result": 5.0},
                max_latency_ms=5000,
            ),
            EvalCase(
                id="calc_multiply",
                endpoint="calc.compute",
                intent="Compute 7 * 8",
                expected={"expression": "7.0 * 8.0", "result": 56.0},
                max_latency_ms=5000,
            ),
            # Inventory — contains + custom judge (no expected -> ExactMatch is a no-op)
            EvalCase(
                id="inventory_widget_a",
                endpoint="inventory.check",
                intent="Check stock for widget-a",
                expected={
                    "sku": "widget-a",
                    "name": "Widget A",
                    "in_stock": True,
                    "quantity": 142,
                },
                contains=["Widget A"],
                max_latency_ms=5000,
            ),
            EvalCase(
                id="inventory_widget_b_oos",
                endpoint="inventory.check",
                intent="Check stock for widget-b",
                expected={
                    "sku": "widget-b",
                    "name": "Widget B",
                    "in_stock": False,
                    "quantity": 0,
                },
                contains=["Widget B"],
                max_latency_ms=5000,
            ),
        ],
        judges=[
            ExactMatchJudge(),
            ContainsJudge(),
            LatencyJudge(),
            CostJudge(),
            PositiveQuantityJudge(),
        ],
    )


def build_schema_eval_set() -> EvalSet:
    """A separate eval set that demonstrates PydanticSchemaJudge.

    Schema judges validate against a *specific* Pydantic model, so
    they belong on eval sets whose cases all return the same shape.
    This set exercises only the weather endpoint and verifies that
    every response validates against ``WeatherForecast``.
    """
    return EvalSet(
        name="weather_schema",
        cases=[
            EvalCase(id="schema_tokyo", endpoint="weather.forecast", intent="Weather in Tokyo"),
            EvalCase(id="schema_london", endpoint="weather.forecast", intent="Weather in London"),
            EvalCase(id="schema_unknown", endpoint="weather.forecast", intent="Weather in Mars"),
        ],
        judges=[PydanticSchemaJudge(model=WeatherForecast)],
    )


# ---------------------------------------------------------------------------
# 7. Eval endpoints — run the suite from inside the app
# ---------------------------------------------------------------------------


@app.agent_endpoint(
    name="eval.run",
    description="Run the programmatic eval suite and return the report.",
)
async def eval_run(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Execute every case in both programmatic eval sets.

    The runner hits the *same app* via Starlette's TestClient, so
    no external server needs to be running. This is the pattern for
    adding a self-evaluation probe to a production service — hit
    ``POST /agent/eval.run`` and assert ``all_passed`` in your
    monitoring.
    """
    runner = EvalRunner(app)

    main_report: EvalReport = await asyncio.to_thread(_run_sync, runner, build_programmatic_eval_set())
    schema_report: EvalReport = await asyncio.to_thread(_run_sync, runner, build_schema_eval_set())

    main_json = main_report.to_json()
    schema_json = schema_report.to_json()
    return {
        "suites": [
            {**main_json, "all_passed": main_report.all_passed},
            {**schema_json, "all_passed": schema_report.all_passed},
        ],
        "total_cases": main_report.total + schema_report.total,
        "total_passed": main_report.passed + schema_report.passed,
        "total_failed": main_report.failed + schema_report.failed,
        "all_passed": main_report.all_passed and schema_report.all_passed,
    }


@app.agent_endpoint(
    name="eval.run_yaml",
    description="Load and run a YAML eval set from disk.",
)
async def eval_run_yaml(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Load the companion YAML file and run it.

    Demonstrates ``load_eval_set()`` — the same function the
    ``agenticapi eval`` CLI calls. The YAML format is documented in
    ``evals/golden.yaml`` alongside this file.
    """
    yaml_path = Path(__file__).parent / "evals" / "golden.yaml"
    eval_set = load_eval_set(yaml_path)
    runner = EvalRunner(app)
    report: EvalReport = await asyncio.to_thread(_run_sync, runner, eval_set)
    json_report = report.to_json()
    json_report["all_passed"] = report.all_passed
    return json_report


def _run_sync(runner: EvalRunner, eval_set: EvalSet) -> EvalReport:
    """Bridge: EvalRunner.run is async, but TestClient needs a sync context."""
    import asyncio as _aio

    loop = _aio.new_event_loop()
    try:
        return loop.run_until_complete(runner.run(eval_set))
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 8. Exports for the e2e test
# ---------------------------------------------------------------------------

__all__ = [
    "CalcResult",
    "InventoryItem",
    "PositiveQuantityJudge",
    "WeatherForecast",
    "app",
    "build_programmatic_eval_set",
    "build_schema_eval_set",
]
