"""EvalSet, EvalCase, EvalRunner (Phase C6).

Declarative regression gates for agent endpoints.

Why a dedicated runner (not pytest).
    pytest tests are the wrong level of abstraction for agent
    eval. pytest cares about whether the code ran; eval cares
    about whether the *behaviour* met expectations. Judges need
    to answer questions pytest doesn't know how to frame —
    "was the latency OK", "did the schema match", "did the
    result contain every required phrase". A dedicated runner
    also gives CI output a consistent JSON report that diffs
    nicely across runs.

YAML format:

.. code-block:: yaml

    name: orders_golden
    cases:
      - id: q_count_2024
        intent: "How many orders do we have from 2024?"
        endpoint: orders.query
        expected:
          count: 137
        judges:
          - type: exact_match
          - type: latency
            max_ms: 2500
          - type: cost
            max_usd: 0.01

The runner's loop:

1. For each case, POST ``{"intent": case.intent}`` to
   ``/agent/{endpoint}`` via Starlette's ``TestClient``.
2. Time the request and stash the response.
3. Fan out every configured judge; a case passes iff every
   judge passes.
4. Aggregate case outcomes into an :class:`EvalReport`.

The CLI wraps this in ``agenticapi eval`` which also handles
YAML parsing, app loading, and JSON/text output.
"""

from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml  # type: ignore[import-untyped]

from agenticapi.evaluation.judges import (
    ContainsJudge,
    CostJudge,
    EvalJudge,
    ExactMatchJudge,
    JudgeResult,
    LatencyJudge,
    PydanticSchemaJudge,
)

if TYPE_CHECKING:
    from agenticapi.app import AgenticApp

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EvalCase:
    """One test case in an :class:`EvalSet`.

    Attributes:
        id: Stable identifier — used as the reporting key.
        endpoint: Endpoint name (without the ``/agent/`` prefix)
            to POST this case to.
        intent: The natural-language intent to send.
        expected: Optional expected result for
            :class:`ExactMatchJudge`. Ignored when that judge is
            not attached.
        contains: Optional list of substrings the result must
            contain (for :class:`ContainsJudge`).
        max_latency_ms: Optional wall-clock budget for
            :class:`LatencyJudge`.
        max_cost_usd: Optional cost budget for :class:`CostJudge`.
        metadata: Arbitrary dict carried into the report for
            extension judges.
    """

    id: str
    endpoint: str
    intent: str
    expected: Any = None
    contains: list[str] = field(default_factory=list)
    max_latency_ms: float | None = None
    max_cost_usd: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvalSet:
    """A named collection of :class:`EvalCase`s plus the judges to run.

    The same set of judges is applied to every case; case-specific
    configuration (``expected``, ``max_latency_ms``, etc.) lives on
    the case itself so a single :class:`ExactMatchJudge` instance
    can serve the whole set.
    """

    name: str
    cases: list[EvalCase] = field(default_factory=list)
    judges: list[EvalJudge] = field(default_factory=list)


@dataclass(slots=True)
class EvalResult:
    """Outcome of running one :class:`EvalCase`.

    Attributes:
        case_id: The case identifier.
        endpoint: The endpoint the case hit.
        passed: ``True`` iff every judge passed.
        judge_results: One entry per configured judge.
        duration_ms: Wall-clock duration of the live request.
        live_result: The handler's return value, extracted from
            the Starlette response.
        error: Set when the live request errored out before any
            judge could run (e.g. the endpoint 500'd).
    """

    case_id: str
    endpoint: str
    passed: bool
    judge_results: list[JudgeResult] = field(default_factory=list)
    duration_ms: float = 0.0
    live_result: Any = None
    error: str | None = None


@dataclass(slots=True)
class EvalReport:
    """Aggregated outcome of running an entire :class:`EvalSet`."""

    set_name: str
    results: list[EvalResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.total > 0

    def to_json(self) -> dict[str, Any]:
        """JSON-serialisable representation for the CLI report."""
        return {
            "set_name": self.set_name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "results": [
                {
                    "case_id": r.case_id,
                    "endpoint": r.endpoint,
                    "passed": r.passed,
                    "duration_ms": round(r.duration_ms, 3),
                    "error": r.error,
                    "judges": [
                        {
                            "name": j.name,
                            "passed": j.passed,
                            "message": j.message,
                            "details": j.details,
                        }
                        for j in r.judge_results
                    ],
                    "live_result": r.live_result,
                }
                for r in self.results
            ],
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class EvalRunner:
    """Runs an :class:`EvalSet` against a live :class:`AgenticApp`.

    The runner is intentionally minimal — it's a thin loop over
    cases + judges. Parallelism, retries, and rate-limiting are
    left to callers because real deployments have wildly different
    constraints here (local test vs. rate-limited cloud backend).
    """

    def __init__(self, app: AgenticApp) -> None:
        self._app = app

    async def run(self, eval_set: EvalSet) -> EvalReport:
        """Execute every case in ``eval_set`` and return a report."""
        from starlette.testclient import TestClient

        client = TestClient(self._app)
        report = EvalReport(set_name=eval_set.name)
        for case in eval_set.cases:
            report.results.append(self._run_case(client, case, eval_set.judges))
        logger.info(
            "eval_run_complete",
            set_name=eval_set.name,
            total=report.total,
            passed=report.passed,
            failed=report.failed,
        )
        return report

    def _run_case(
        self,
        client: Any,
        case: EvalCase,
        judges: list[EvalJudge],
    ) -> EvalResult:
        """Send one case through the app and judge the result."""
        start = time.monotonic()
        try:
            response = client.post(
                f"/agent/{case.endpoint}",
                json={"intent": case.intent},
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            return EvalResult(
                case_id=case.id,
                endpoint=case.endpoint,
                passed=False,
                duration_ms=duration_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
        duration_ms = (time.monotonic() - start) * 1000

        try:
            live_payload = response.json()
        except json.JSONDecodeError:
            live_payload = response.text

        if response.status_code >= 400:
            return EvalResult(
                case_id=case.id,
                endpoint=case.endpoint,
                passed=False,
                duration_ms=duration_ms,
                live_result=live_payload,
                error=f"HTTP {response.status_code}",
            )

        judge_results: list[JudgeResult] = []
        for judge in judges:
            try:
                result = judge.evaluate(
                    case=case,
                    live_payload=live_payload,
                    duration_ms=duration_ms,
                )
            except Exception as exc:
                result = JudgeResult(
                    name=getattr(judge, "name", type(judge).__name__),
                    passed=False,
                    message=f"judge raised: {type(exc).__name__}: {exc}",
                )
            judge_results.append(result)

        # Extract the inner result for the report.
        live_result = live_payload
        if isinstance(live_payload, dict) and "result" in live_payload:
            live_result = live_payload["result"]

        passed = all(j.passed for j in judge_results)
        return EvalResult(
            case_id=case.id,
            endpoint=case.endpoint,
            passed=passed,
            judge_results=judge_results,
            duration_ms=duration_ms,
            live_result=live_result,
        )


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def load_eval_set(path: str | Path) -> EvalSet:
    """Load an :class:`EvalSet` from a YAML file.

    Judge types are resolved against the built-in catalogue;
    ``pydantic_schema`` additionally imports the specified model
    via a dotted path (``app.schemas.OrderCount``).
    """
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"EvalSet YAML must be a mapping, got {type(data).__name__}")

    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("EvalSet YAML must specify a non-empty 'name'")

    raw_cases = data.get("cases") or []
    if not isinstance(raw_cases, list):
        raise ValueError("EvalSet YAML 'cases' must be a list")

    cases: list[EvalCase] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError(f"EvalCase entry must be a mapping, got {type(raw).__name__}")
        case_id = raw.get("id")
        endpoint = raw.get("endpoint")
        intent = raw.get("intent")
        if not isinstance(case_id, str) or not isinstance(endpoint, str) or not isinstance(intent, str):
            raise ValueError(f"EvalCase missing required fields (id, endpoint, intent): {raw}")
        cases.append(
            EvalCase(
                id=case_id,
                endpoint=endpoint,
                intent=intent,
                expected=raw.get("expected"),
                contains=list(raw.get("contains") or []),
                max_latency_ms=_maybe_float(raw.get("max_latency_ms")),
                max_cost_usd=_maybe_float(raw.get("max_cost_usd")),
                metadata=dict(raw.get("metadata") or {}),
            )
        )

    raw_judges = data.get("judges") or [{"type": "exact_match"}]
    if not isinstance(raw_judges, list):
        raise ValueError("EvalSet YAML 'judges' must be a list")
    judges = [_build_judge(entry) for entry in raw_judges]
    return EvalSet(name=name, cases=cases, judges=judges)


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_judge(entry: Any) -> EvalJudge:
    """Turn a YAML judge entry into a judge instance."""
    if not isinstance(entry, dict):
        raise ValueError(f"Judge entry must be a mapping, got {type(entry).__name__}")
    kind = entry.get("type")
    if not isinstance(kind, str):
        raise ValueError(f"Judge entry missing 'type': {entry}")
    if kind == "exact_match":
        return ExactMatchJudge()
    if kind == "contains":
        return ContainsJudge()
    if kind == "latency":
        return LatencyJudge()
    if kind == "cost":
        return CostJudge()
    if kind == "pydantic_schema":
        model_path = entry.get("model")
        if not isinstance(model_path, str) or (":" not in model_path and "." not in model_path):
            raise ValueError(f"pydantic_schema judge needs 'model: module.path:Class' (got {model_path!r})")
        return PydanticSchemaJudge(model=_import_attr(model_path))
    raise ValueError(f"Unknown judge type: {kind!r}")


def _import_attr(dotted_path: str) -> Any:
    """Import a dotted-path attribute (module.path:attr or module.path.attr)."""
    if ":" in dotted_path:
        module_name, attr = dotted_path.split(":", 1)
    else:
        module_name, _, attr = dotted_path.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"Invalid dotted path: {dotted_path!r}")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


__all__ = [
    "EvalCase",
    "EvalReport",
    "EvalResult",
    "EvalRunner",
    "EvalSet",
    "load_eval_set",
]
