"""Evaluation harness (Phase C6).

Regression gate for agent endpoints. Declarative YAML (or
programmatic) :class:`EvalSet`s loop through a list of
:class:`EvalCase`s, POST each to the live app, and apply
judges that answer "did the result meet expectations?"

Public API re-exports the common types so callers don't have to
pick between ``agenticapi.evaluation.runner`` and
``agenticapi.evaluation.judges`` — one import is enough for 99%
of use cases.

See :doc:`/development/eval.md` for the full tutorial; the CLI
entry point ``agenticapi eval`` lives in
:mod:`agenticapi.cli.eval`.
"""

from __future__ import annotations

from agenticapi.evaluation.judges import (
    ContainsJudge,
    CostJudge,
    EvalJudge,
    ExactMatchJudge,
    JudgeResult,
    LatencyJudge,
    PydanticSchemaJudge,
)
from agenticapi.evaluation.runner import (
    EvalCase,
    EvalReport,
    EvalResult,
    EvalRunner,
    EvalSet,
    load_eval_set,
)

__all__ = [
    "ContainsJudge",
    "CostJudge",
    "EvalCase",
    "EvalJudge",
    "EvalReport",
    "EvalResult",
    "EvalRunner",
    "EvalSet",
    "ExactMatchJudge",
    "JudgeResult",
    "LatencyJudge",
    "PydanticSchemaJudge",
    "load_eval_set",
]
