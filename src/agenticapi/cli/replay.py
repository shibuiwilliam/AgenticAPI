"""Replay CLI primitive (Phase A6).

Why replay exists.

    Phase A3 added :class:`SqliteAuditRecorder`, so every agent
    request now leaves a durable trace. A trace without a replay
    primitive is a corpse: you can look at it but you can't use it
    to catch regressions, validate new prompts, or reproduce a bug
    report. Replay closes that loop — it re-runs a historical
    request through the current live pipeline and returns a diff
    against the recorded result.

    Concretely, ``agenticapi replay`` takes a trace id, loads the
    :class:`~agenticapi.harness.audit.trace.ExecutionTrace` from the
    store, finds the matching endpoint on the live
    :class:`~agenticapi.AgenticApp`, POSTs the original intent
    through Starlette's :class:`TestClient`, and prints a JSON diff
    summarising what changed between the historical result and the
    current one.

What's in scope.

    * Single-trace replay (`agenticapi replay <trace_id>`).
    * A programmatic :func:`replay` function the CLI wraps, so test
      suites and eval harnesses (C7) can embed replay without
      spawning a subprocess.
    * A small :class:`ReplayResult` dataclass that captures:
      historical ``intent_raw``, historical result, live result, a
      JSON diff, error message (if the live run failed), and the
      walltime duration of the replay itself.

What's intentionally out of scope (lands in C6/C7).

    * Regression gating against thresholds — the eval harness owns
      that decision.
    * Bulk replay over a time window — once the single-trace path
      works, a for-loop plus :meth:`SqliteAuditRecorder.iter_since`
      is a trivial wrapper.
    * Judges (cost, latency, semantic match) — those belong to the
      eval harness, not this primitive.

How the app gets loaded.

    The CLI accepts ``--app myapp:app``, the same syntax
    ``agenticapi dev`` already uses. The module is imported and the
    attribute is read — there is no reload or watchdog involvement,
    so replay can run from inside tests and notebooks too.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agenticapi.app import AgenticApp
    from agenticapi.harness.audit.trace import ExecutionTrace

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReplayResult:
    """Structured outcome of a :func:`replay` call.

    Attributes:
        trace_id: Identifier of the replayed historical trace.
        endpoint_name: Endpoint the historical request ran against.
        intent_raw: The original natural-language request that was
            replayed — handy for humans reading the CLI output and
            for eval reports.
        historical_result: The result stored on the historical
            trace. May be ``None`` when the original request errored
            or didn't return JSON.
        live_result: The result of the fresh run. Shape depends on
            the endpoint — typically the dict payload Starlette
            returned under ``data["result"]``.
        diff: JSON-serialisable description of the structural
            differences between ``historical_result`` and
            ``live_result``. Empty when the two are identical.
        status: ``"identical"`` / ``"different"`` / ``"error"``.
        error: Error message from the live run, when applicable.
        duration_ms: Wall-clock milliseconds the replay took.
    """

    trace_id: str
    endpoint_name: str
    intent_raw: str
    historical_result: Any
    live_result: Any
    diff: dict[str, Any] = field(default_factory=dict)
    status: str = "identical"
    error: str | None = None
    duration_ms: float = 0.0

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-friendly dict suitable for CLI output / eval reports."""
        return {
            "trace_id": self.trace_id,
            "endpoint_name": self.endpoint_name,
            "intent_raw": self.intent_raw,
            "historical_result": self.historical_result,
            "live_result": self.live_result,
            "diff": self.diff,
            "status": self.status,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 3),
        }


# ---------------------------------------------------------------------------
# Diffing helpers
# ---------------------------------------------------------------------------


def _diff_values(historical: Any, live: Any) -> dict[str, Any]:
    """Produce a small structural diff suitable for human review.

    The diff format is deliberately minimal — three keys at most
    (``added``, ``removed``, ``changed``) — so CLI output stays
    readable. For list values the diff reports length delta +
    index-level changes; for dicts it recurses one level.

    Returns an empty dict when the two values are equal.
    """
    if historical == live:
        return {}
    if isinstance(historical, dict) and isinstance(live, dict):
        added = sorted(k for k in live if k not in historical)
        removed = sorted(k for k in historical if k not in live)
        changed: dict[str, dict[str, Any]] = {}
        for key in historical.keys() & live.keys():
            if historical[key] != live[key]:
                changed[key] = {"before": historical[key], "after": live[key]}
        out: dict[str, Any] = {}
        if added:
            out["added"] = added
        if removed:
            out["removed"] = removed
        if changed:
            out["changed"] = changed
        return out
    if isinstance(historical, list) and isinstance(live, list):
        out_list: dict[str, Any] = {
            "length_before": len(historical),
            "length_after": len(live),
        }
        if historical != live:
            max_reported = 5  # keep CLI output compact
            changes: list[dict[str, Any]] = []
            for idx in range(min(len(historical), len(live))):
                if historical[idx] != live[idx]:
                    changes.append({"index": idx, "before": historical[idx], "after": live[idx]})
                    if len(changes) >= max_reported:
                        break
            if changes:
                out_list["changes"] = changes
        return out_list
    # Scalars or mixed types — report the raw before/after.
    return {"before": historical, "after": live}


# ---------------------------------------------------------------------------
# App loading
# ---------------------------------------------------------------------------


def _load_app(app_path: str) -> AgenticApp:
    """Import an :class:`AgenticApp` from a ``module:attr`` string.

    Matches the import syntax ``agenticapi dev`` already uses. Adds
    the current working directory to ``sys.path`` first so users can
    run ``agenticapi replay ... --app myapp:app`` from their project
    root without setting ``PYTHONPATH``.
    """
    import os

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


# ---------------------------------------------------------------------------
# Core replay implementation
# ---------------------------------------------------------------------------


async def replay(
    trace_id: str,
    *,
    app: AgenticApp,
    recorder: Any | None = None,
) -> ReplayResult:
    """Replay a historical execution trace through the live app.

    Looks up ``trace_id`` in the app's audit store (or in an
    explicit ``recorder`` if one is provided — handy for tests that
    want to pass an in-memory recorder directly), POSTs the
    historical intent through a fresh Starlette :class:`TestClient`,
    and returns a :class:`ReplayResult` containing both outcomes
    plus a diff.

    Args:
        trace_id: The historical trace identifier.
        app: The :class:`AgenticApp` whose pipeline the replay runs
            against. Typically the same app that recorded the trace,
            though replaying against a newer version of the same app
            is the whole point of the regression workflow.
        recorder: Optional audit recorder to query for the trace.
            When ``None``, the app's harness recorder is used.

    Returns:
        A :class:`ReplayResult` summarising the replay.

    Raises:
        LookupError: The trace id was not found in the recorder.
        ValueError: The app has no harness (and no ``recorder`` was
            provided) so there's nowhere to look up the trace.
    """
    from starlette.testclient import TestClient

    start = time.monotonic()
    effective_recorder = recorder
    if effective_recorder is None:
        if app.harness is None:
            raise ValueError(
                "replay() needs an audit recorder. Pass one explicitly or "
                "construct the AgenticApp with a HarnessEngine that has one."
            )
        effective_recorder = app.harness.audit_recorder

    trace = _load_trace(effective_recorder, trace_id)
    if trace is None:
        raise LookupError(f"No audit trace with trace_id={trace_id!r} in the configured recorder")

    logger.info(
        "replay_start",
        trace_id=trace_id,
        endpoint=trace.endpoint_name,
        intent_action=trace.intent_action,
    )

    client = TestClient(app)
    try:
        response = client.post(
            f"/agent/{trace.endpoint_name}",
            json={"intent": trace.intent_raw},
        )
    except Exception as exc:
        duration_ms = (time.monotonic() - start) * 1000
        return ReplayResult(
            trace_id=trace_id,
            endpoint_name=trace.endpoint_name,
            intent_raw=trace.intent_raw,
            historical_result=trace.execution_result,
            live_result=None,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=duration_ms,
        )

    live_payload: Any
    try:
        live_payload = response.json()
    except json.JSONDecodeError:
        live_payload = response.text

    duration_ms = (time.monotonic() - start) * 1000

    if response.status_code >= 400:
        return ReplayResult(
            trace_id=trace_id,
            endpoint_name=trace.endpoint_name,
            intent_raw=trace.intent_raw,
            historical_result=trace.execution_result,
            live_result=live_payload,
            status="error",
            error=f"HTTP {response.status_code}",
            duration_ms=duration_ms,
        )

    # Starlette wraps the handler's return value under ``result`` in
    # the non-streaming path. Fall back to the whole payload when the
    # shape doesn't match.
    live_result: Any = live_payload
    if isinstance(live_payload, dict) and "result" in live_payload:
        live_result = live_payload["result"]

    diff = _diff_values(trace.execution_result, live_result)
    status = "identical" if not diff else "different"
    return ReplayResult(
        trace_id=trace_id,
        endpoint_name=trace.endpoint_name,
        intent_raw=trace.intent_raw,
        historical_result=trace.execution_result,
        live_result=live_result,
        diff=diff,
        status=status,
        duration_ms=duration_ms,
    )


def _load_trace(recorder: Any, trace_id: str) -> ExecutionTrace | None:
    """Look up ``trace_id`` across both the sync and async recorder shapes.

    The in-memory recorder and the sqlite recorder expose
    ``get_by_id`` synchronously; any exotic recorder that only
    exposes ``get_records`` still works because we fall back to a
    linear scan in that case.
    """
    getter = getattr(recorder, "get_by_id", None)
    if callable(getter):
        return getter(trace_id)  # type: ignore[no-any-return]
    # Fallback: linear scan of get_records().
    scanner = getattr(recorder, "get_records", None)
    if callable(scanner):
        for trace in scanner():
            if trace.trace_id == trace_id:
                return trace  # type: ignore[no-any-return]
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def run_replay_cli(*, trace_id: str, app_path: str) -> int:
    """Command-line entry point invoked by ``agenticapi replay``.

    Returns an integer exit code suitable for ``sys.exit``:

    * ``0`` — replay succeeded and the live result matched the
      historical one.
    * ``1`` — replay succeeded but results differed. Output contains
      the JSON diff.
    * ``2`` — replay errored (trace missing, live pipeline failed,
      etc.). Error details are in the ``error`` field of the output.
    """
    try:
        app = _load_app(app_path)
    except (ValueError, AttributeError, TypeError, ImportError) as exc:
        sys.stderr.write(f"agenticapi replay: failed to load app {app_path!r}: {exc}\n")
        return 2

    try:
        result = asyncio.run(replay(trace_id, app=app))
    except LookupError as exc:
        sys.stderr.write(f"agenticapi replay: {exc}\n")
        return 2
    except ValueError as exc:
        sys.stderr.write(f"agenticapi replay: {exc}\n")
        return 2

    sys.stdout.write(json.dumps(result.to_json(), indent=2, default=str) + "\n")
    if result.status == "identical":
        return 0
    if result.status == "different":
        return 1
    return 2


__all__ = [
    "ReplayResult",
    "replay",
    "run_replay_cli",
]
