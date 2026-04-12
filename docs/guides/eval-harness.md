# Eval Harness

AgenticAPI ships a dedicated evaluation harness for regression-testing agent endpoints. Where pytest tests verify that *code ran*, eval sets verify that the *behaviour met expectations*: the right answer, fast enough, under budget, matching the schema, containing key phrases.

## Why a dedicated runner?

pytest cares about code execution. Eval cares about behaviour quality. Judges answer questions pytest cannot frame -- "did the latency stay under 2.5 seconds?", "does the result match this Pydantic schema?", "did the response contain every required phrase?" A dedicated runner also produces a consistent JSON report that diffs cleanly across runs.

## Core types

| Type | Purpose |
|---|---|
| `EvalCase` | One test case: endpoint, intent, expected result, per-case budgets |
| `EvalSet` | A named collection of cases plus the judges to run |
| `EvalRunner` | Executes cases against a live `AgenticApp` and collects results |
| `EvalReport` | Aggregated outcome with pass/fail per case, per judge |
| `EvalJudge` | Protocol every judge satisfies |

## Programmatic construction

```python
from agenticapi.evaluation.runner import EvalCase, EvalRunner, EvalSet
from agenticapi.evaluation.judges import (
    ContainsJudge,
    ExactMatchJudge,
    LatencyJudge,
)

eval_set = EvalSet(
    name="orders_golden",
    cases=[
        EvalCase(
            id="count_2024",
            endpoint="orders.query",
            intent="How many orders from 2024?",
            expected={"count": 137},
            max_latency_ms=2500,
        ),
        EvalCase(
            id="top_customer",
            endpoint="orders.query",
            intent="Who is the top customer?",
            contains=["Acme Corp"],
            max_latency_ms=3000,
        ),
    ],
    judges=[ExactMatchJudge(), ContainsJudge(), LatencyJudge()],
)

runner = EvalRunner(app)
report = await runner.run(eval_set)
print(f"{report.passed}/{report.total} passed")
```

The runner POSTs `{"intent": case.intent}` to `/agent/{endpoint}` via Starlette's `TestClient`, times the request, fans out every judge, and marks a case as passed only when every judge passes.

## YAML format

Eval sets can be defined in YAML files, which is the format the CLI consumes:

```yaml
name: golden_yaml_suite

judges:
  - type: exact_match
  - type: contains
  - type: latency

cases:
  - id: weather_tokyo
    endpoint: weather.forecast
    intent: "Weather in Tokyo"
    expected:
      city: Tokyo
      temperature_c: 22.5
      condition: partly cloudy
    contains:
      - Tokyo
      - partly cloudy
    max_latency_ms: 5000

  - id: calc_add
    endpoint: calc.compute
    intent: "2 + 3"
    expected:
      expression: "2.0 + 3.0"
      result: 5.0
    max_latency_ms: 5000
```

Load it with:

```python
from agenticapi.evaluation.runner import load_eval_set

eval_set = load_eval_set("evals/golden.yaml")
```

## Five built-in judges

| Judge | What it checks |
|---|---|
| `ExactMatchJudge` | Structural equality (`==`) between `case.expected` and the live result |
| `ContainsJudge` | Every string in `case.contains` appears in the JSON-rendered result |
| `LatencyJudge` | Wall-clock duration is below `case.max_latency_ms` |
| `CostJudge` | LLM cost (from `cost_usd` in response) is at or below `case.max_cost_usd` |
| `PydanticSchemaJudge` | Live result validates against a Pydantic model |

The `PydanticSchemaJudge` is configured in YAML with a dotted import path:

```yaml
judges:
  - type: pydantic_schema
    model: myapp.schemas:WeatherResult
```

## Custom judges

Any object with an `evaluate(*, case, live_payload, duration_ms)` method and a `name` property satisfies the `EvalJudge` protocol:

```python
from agenticapi.evaluation.judges import EvalJudge, JudgeResult
from agenticapi.evaluation.runner import EvalCase


class PositiveResultJudge:
    name = "positive_result"

    def evaluate(
        self, *, case: EvalCase, live_payload: dict, duration_ms: float
    ) -> JudgeResult:
        result = live_payload.get("result", {})
        value = result.get("value", 0)
        if value > 0:
            return JudgeResult(name=self.name, passed=True)
        return JudgeResult(
            name=self.name,
            passed=False,
            message=f"Expected positive value, got {value}",
        )
```

Register it alongside the built-in judges:

```python
eval_set = EvalSet(
    name="custom",
    cases=[...],
    judges=[ExactMatchJudge(), PositiveResultJudge()],
)
```

## CLI usage

The `agenticapi eval` command loads a YAML eval set, spins up the app, and runs the suite:

```bash
agenticapi eval --app myapp:app --set evals/golden.yaml
```

The output is a JSON report with pass/fail per case, per judge, plus timing and optional cost data.

## Self-evaluating endpoint pattern

A useful production pattern is an endpoint that runs the eval suite against the same app, returning the `EvalReport` as JSON. This serves as a health-check-style probe:

```python
@app.agent_endpoint(name="eval.run")
async def run_eval(intent: Intent, context: AgentContext) -> dict:
    runner = EvalRunner(app)
    report = await runner.run(eval_set)
    return report.to_json()
```

```bash
curl -s -X POST http://127.0.0.1:8000/agent/eval.run \
    -H "Content-Type: application/json" \
    -d '{"intent": "Run eval suite"}' | python3 -m json.tool
```

## Runnable example

See [`examples/23_eval_harness/app.py`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/23_eval_harness) -- a deterministic app with three endpoints evaluated by every built-in judge, plus a custom judge and both programmatic and YAML eval sets.

```bash
uvicorn examples.23_eval_harness.app:app --reload
```

See also:

- [Testing](testing.md) -- pytest-based testing for agent endpoints
- [Cost Budgeting](cost-budgeting.md) -- the `CostJudge` checks `BudgetPolicy` cost annotations
- [API Reference → Types & Exceptions](../api/types.md) -- `EvalReport.to_json()` shape
