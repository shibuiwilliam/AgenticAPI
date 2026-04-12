"""Eval CLI entry point (Phase C6).

Wraps :class:`agenticapi.evaluation.runner.EvalRunner` so
operators can run a regression gate against a live app from the
command line:

.. code-block:: bash

    agenticapi eval --set eval/orders.yaml --app myapp:app
    agenticapi eval --set eval/orders.yaml --app myapp:app --format text

Exit codes:

* ``0`` — every case passed.
* ``1`` — at least one case failed (regression detected).
* ``2`` — the CLI could not even start (app failed to load, YAML
  invalid, etc.).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from typing import TYPE_CHECKING

import structlog

from agenticapi.evaluation.runner import EvalRunner, load_eval_set

if TYPE_CHECKING:
    from agenticapi.app import AgenticApp
    from agenticapi.evaluation.runner import EvalReport

logger = structlog.get_logger(__name__)


def _load_app(app_path: str) -> AgenticApp:
    """Import ``module:attr`` and return the :class:`AgenticApp`.

    Mirrors the loader used by :mod:`agenticapi.cli.replay`.
    """
    from agenticapi.app import AgenticApp

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    if ":" not in app_path:
        raise ValueError(f"--app must be 'module:attr' (got {app_path!r})")
    module_name, attr = app_path.split(":", 1)
    module = importlib.import_module(module_name)
    app = getattr(module, attr, None)
    if app is None:
        raise AttributeError(f"Module {module_name!r} has no attribute {attr!r}")
    if not isinstance(app, AgenticApp):
        raise TypeError(
            f"Attribute {attr!r} on {module_name!r} is not an AgenticApp instance (got {type(app).__name__})"
        )
    return app


def _render_text_report(report: EvalReport) -> str:
    """Human-friendly text rendering for the CLI default output."""
    lines: list[str] = []
    lines.append(f"Eval set: {report.set_name}")
    lines.append(f"  total:  {report.total}")
    lines.append(f"  passed: {report.passed}")
    lines.append(f"  failed: {report.failed}")
    lines.append("")
    for result in report.results:
        marker = "PASS" if result.passed else "FAIL"
        lines.append(f"[{marker}] {result.case_id} ({result.endpoint}) {result.duration_ms:.0f} ms")
        if result.error:
            lines.append(f"    error: {result.error}")
        for judge in result.judge_results:
            status = "ok" if judge.passed else "failed"
            lines.append(f"    - {judge.name}: {status}{' — ' + judge.message if judge.message else ''}")
    return "\n".join(lines) + "\n"


def run_eval_cli(
    *,
    eval_set_path: str,
    app_path: str,
    fmt: str = "text",
) -> int:
    """Command-line entry point invoked by ``agenticapi eval``.

    Loads the YAML eval set and app, runs the suite, prints the
    report (text or JSON), and returns an exit code.
    """
    try:
        app = _load_app(app_path)
    except (ValueError, AttributeError, TypeError, ImportError) as exc:
        sys.stderr.write(f"agenticapi eval: failed to load app {app_path!r}: {exc}\n")
        return 2

    try:
        eval_set = load_eval_set(eval_set_path)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"agenticapi eval: failed to load eval set {eval_set_path!r}: {exc}\n")
        return 2

    runner = EvalRunner(app)
    report = asyncio.run(runner.run(eval_set))

    if fmt == "json":
        sys.stdout.write(json.dumps(report.to_json(), indent=2, default=str) + "\n")
    else:
        sys.stdout.write(_render_text_report(report))

    if report.all_passed:
        return 0
    return 1


__all__ = ["run_eval_cli"]
