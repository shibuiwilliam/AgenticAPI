"""Built-in judges for the evaluation harness (Phase C6).

Judges answer the regression question: *did this case's response
match what we expected?* Each judge is a small callable that takes
the case, the live response, and some timing metadata, and returns
a :class:`JudgeResult` with ``passed`` + an optional human-readable
``message``.

The ``EvalJudge`` protocol is intentionally minimal so users can
drop in their own judges without subclassing: any object with an
``evaluate(*, case, result, live_payload, duration_ms)`` method and
a ``name`` property satisfies it. The runner fans out to every
registered judge and treats a case as **passed** only when every
judge passes — the logical AND is the right default for a
regression gate.

The default set of judges covers the spec in
:doc:`/CLAUDE_ENHANCE`'s C6 section:

* :class:`ExactMatchJudge` — structural equality to a stored value
* :class:`ContainsJudge` — substring check on JSON-rendered result
* :class:`PydanticSchemaJudge` — validate result against a pydantic model
* :class:`LatencyJudge` — wall-clock upper bound
* :class:`CostJudge` — LLM-token cost upper bound (optional;
  requires the response to carry a ``cost_usd`` annotation)

LLM-judge and groundedness judges (which would require calling an
LLM) are intentionally out of scope for C6 because they introduce
a recursive dependency and significant cost; C7 will land them as
opt-in evaluators.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pydantic import BaseModel

    from agenticapi.evaluation.runner import EvalCase


@dataclass(slots=True, frozen=True)
class JudgeResult:
    """Outcome of applying one judge to one case.

    Attributes:
        name: Judge identifier, e.g. ``"exact_match"``.
        passed: ``True`` when the case satisfies this judge.
        message: Optional human-readable explanation. Empty on
            success; a brief reason on failure (``"latency 2714 ms
            > 2500 ms"``).
        details: Optional machine-readable diagnostic dict the CLI
            serialises into the report JSON.
    """

    name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] | None = None


@runtime_checkable
class EvalJudge(Protocol):
    """Protocol every judge satisfies.

    ``evaluate`` is intentionally keyword-only so judges never mix
    up the case and the response. Implementations should be pure
    functions of their inputs — no side effects, no I/O beyond
    reading the case — so the runner can safely parallelise them.
    """

    name: str

    def evaluate(
        self,
        *,
        case: EvalCase,
        live_payload: Any,
        duration_ms: float,
    ) -> JudgeResult:
        """Return the outcome of applying this judge to one case."""
        ...


# ---------------------------------------------------------------------------
# Built-in judges
# ---------------------------------------------------------------------------


class ExactMatchJudge:
    """Passes when the live result equals ``case.expected`` structurally.

    Uses ``==`` so dicts / lists / primitives all work. Order
    matters for lists (``[1, 2] != [2, 1]``) — this is the right
    default for agent results, which are usually order-significant.
    Callers that want order-insensitive comparison should write a
    custom judge.
    """

    name = "exact_match"

    def evaluate(
        self,
        *,
        case: EvalCase,
        live_payload: Any,
        duration_ms: float,
    ) -> JudgeResult:
        del duration_ms
        result = _extract_result(live_payload)
        if case.expected == result:
            return JudgeResult(name=self.name, passed=True)
        return JudgeResult(
            name=self.name,
            passed=False,
            message=f"expected {case.expected!r}, got {result!r}",
            details={"expected": case.expected, "actual": result},
        )


class ContainsJudge:
    """Passes when every ``contains`` substring appears in the JSON result.

    The judge renders the live result via ``json.dumps`` and checks
    that every configured substring appears in that text. Handy for
    free-form responses where the exact wording varies but a few
    key phrases must be present.

    Configuration lives on the case: ``EvalCase.contains`` is a
    list of strings.
    """

    name = "contains"

    def evaluate(
        self,
        *,
        case: EvalCase,
        live_payload: Any,
        duration_ms: float,
    ) -> JudgeResult:
        del duration_ms
        if not case.contains:
            return JudgeResult(name=self.name, passed=True)
        result = _extract_result(live_payload)
        rendered = json.dumps(result, default=str, ensure_ascii=False)
        missing: list[str] = [needle for needle in case.contains if needle not in rendered]
        if not missing:
            return JudgeResult(name=self.name, passed=True)
        return JudgeResult(
            name=self.name,
            passed=False,
            message=f"missing required substrings: {missing!r}",
            details={"missing": missing},
        )


class LatencyJudge:
    """Passes when wall-clock duration is below ``max_ms``.

    The max is supplied per-case via ``EvalCase.max_latency_ms``;
    when missing, the judge is a no-op (always passes) so the same
    judge can be used across cases with heterogeneous latency
    budgets.
    """

    name = "latency"

    def evaluate(
        self,
        *,
        case: EvalCase,
        live_payload: Any,
        duration_ms: float,
    ) -> JudgeResult:
        del live_payload
        if case.max_latency_ms is None:
            return JudgeResult(name=self.name, passed=True)
        if duration_ms <= case.max_latency_ms:
            return JudgeResult(
                name=self.name,
                passed=True,
                details={"duration_ms": duration_ms, "budget_ms": case.max_latency_ms},
            )
        return JudgeResult(
            name=self.name,
            passed=False,
            message=f"latency {duration_ms:.0f} ms > {case.max_latency_ms} ms",
            details={"duration_ms": duration_ms, "budget_ms": case.max_latency_ms},
        )


class CostJudge:
    """Passes when the observed cost is at or below ``max_cost_usd``.

    Expects the live payload to include a ``cost_usd`` field
    (agent responses that return one via the ``cost_usd`` key in
    the result dict). Missing cost is treated as zero — if your
    harness doesn't surface cost yet, attach a custom judge or
    rely on the BudgetPolicy metric instead.
    """

    name = "cost"

    def evaluate(
        self,
        *,
        case: EvalCase,
        live_payload: Any,
        duration_ms: float,
    ) -> JudgeResult:
        del duration_ms
        if case.max_cost_usd is None:
            return JudgeResult(name=self.name, passed=True)
        cost = _extract_cost(live_payload)
        if cost is None:
            # No cost information — default to "not applicable" pass
            # so cases without cost annotations don't all fail.
            return JudgeResult(
                name=self.name,
                passed=True,
                message="no cost_usd in response; treated as 0",
            )
        if cost <= case.max_cost_usd:
            return JudgeResult(
                name=self.name,
                passed=True,
                details={"cost_usd": cost, "budget_usd": case.max_cost_usd},
            )
        return JudgeResult(
            name=self.name,
            passed=False,
            message=f"cost ${cost:.4f} > ${case.max_cost_usd:.4f}",
            details={"cost_usd": cost, "budget_usd": case.max_cost_usd},
        )


class PydanticSchemaJudge:
    """Passes when the live result validates against a Pydantic model.

    The model is supplied to the judge constructor (not the case)
    because the runtime resolution of a dotted path from YAML is
    a separate concern — the YAML loader ``load_eval_set`` handles
    that import and passes the resolved class here.
    """

    name = "pydantic_schema"

    def __init__(self, model: type[BaseModel]) -> None:
        self.model = model

    def evaluate(
        self,
        *,
        case: EvalCase,
        live_payload: Any,
        duration_ms: float,
    ) -> JudgeResult:
        del case, duration_ms
        from pydantic import ValidationError

        result = _extract_result(live_payload)
        try:
            self.model.model_validate(result)
        except ValidationError as exc:
            return JudgeResult(
                name=self.name,
                passed=False,
                message=f"result does not match {self.model.__name__}: {exc.errors()[:1]}",
                details={"errors": exc.errors(include_input=False)[:5]},
            )
        return JudgeResult(name=self.name, passed=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_result(live_payload: Any) -> Any:
    """Pull the handler's return value out of the Starlette response body.

    Starlette agent responses wrap the handler return under
    ``result``; direct handler responses are the value itself. The
    judges work against the inner value so a YAML ``expected`` can
    be written against the handler's contract rather than the
    framework's wrapper shape.
    """
    if isinstance(live_payload, dict) and "result" in live_payload:
        return live_payload["result"]
    return live_payload


def _extract_cost(live_payload: Any) -> float | None:
    """Pull a ``cost_usd`` float out of the live payload, if present."""
    if isinstance(live_payload, dict):
        if "cost_usd" in live_payload:
            try:
                return float(live_payload["cost_usd"])
            except (TypeError, ValueError):
                return None
        inner = live_payload.get("result")
        if isinstance(inner, dict) and "cost_usd" in inner:
            try:
                return float(inner["cost_usd"])
            except (TypeError, ValueError):
                return None
    return None


__all__ = [
    "ContainsJudge",
    "CostJudge",
    "EvalJudge",
    "ExactMatchJudge",
    "JudgeResult",
    "LatencyJudge",
    "PydanticSchemaJudge",
]
