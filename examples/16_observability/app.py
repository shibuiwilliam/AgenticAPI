"""Observability example: tracing, metrics, and persistent audit.

This is the **operator story** for AgenticAPI. Production agent
systems need answers to three questions at 3 a.m.:

1. *"Is the service healthy right now?"* — **metrics**
2. *"What happened on that request?"* — **tracing**
3. *"Prove to me what the agent did yesterday."* — **persistent audit**

AgenticAPI ships first-class integrations for all three. This example
wires them together into a single small app and exposes them via
standard operator endpoints so you can scrape the service with
Prometheus, follow spans in Jaeger, and query the audit log via
HTTP — all without any LLM or API key.

What this example demonstrates
------------------------------

* **`configure_tracing()` + `configure_metrics()`** — one-line opt-in
  for OpenTelemetry tracing and metrics. Both are no-ops if the
  OpenTelemetry SDK is not installed, so the example runs fine in a
  minimal environment and *upgrades itself* when the SDK is present.
* **Typed metric recording helpers** — `record_request`,
  `record_policy_denial`, `record_llm_usage`, `record_tool_call`,
  `record_budget_block`, `record_sandbox_violation` — called
  explicitly from the handler so you can see exactly what gets
  emitted.
* **Prometheus scrape endpoint** — a custom Starlette `Route` at
  `GET /metrics` that hands back whatever `render_prometheus_exposition()`
  returns. Scrape it with any Prometheus instance.
* **`SqliteAuditRecorder`** — a persistent audit store backed by the
  stdlib `sqlite3` module (zero new dependencies). Survives process
  restarts, bounded by `max_traces`, indexed on `(timestamp DESC)`
  and `(endpoint_name)` for fast dashboard queries.
* **Audit query endpoints** — a small set of HTTP endpoints that use
  the recorder's `get_records`, `count`, and `iter_since` helpers to
  expose the audit log to an operator UI.
* **Manual trace recording** — because the handlers don't go through
  the full LLM-plus-harness pipeline, this example creates and
  records `ExecutionTrace` objects by hand, so you can see exactly
  what shape the audit store wants.
* **Three endpoints with three outcomes** to exercise the metrics
  and audit plumbing:
    - ``ops.ingest`` — succeeds, records a request + "llm" usage
    - ``ops.risky`` — is blocked by a policy denial the example
      simulates, bumping ``agenticapi.policy.denials`` counter
    - ``ops.budget`` — simulates a budget block so the
      ``agenticapi.budget.blocks`` counter moves

No LLM or API key is required. Everything is deterministic so the
test suite can make exact assertions.

Run with::

    uvicorn examples.16_observability.app:app --reload

Or with the CLI::

    agenticapi dev --app examples.16_observability.app:app

Optional — install the OpenTelemetry SDK to get real tracing/metrics
instead of the no-op shim::

    pip install opentelemetry-api opentelemetry-sdk

Walkthrough::

    # 1. Drive some traffic
    curl -X POST http://127.0.0.1:8000/agent/ops.ingest \
        -H "Content-Type: application/json" \
        -d '{"intent": "ingest new document"}'

    # 2. Trigger a policy denial (audit row + policy_denials counter)
    curl -X POST http://127.0.0.1:8000/agent/ops.risky \
        -H "Content-Type: application/json" \
        -d '{"intent": "dangerous operation"}'

    # 3. Trigger a budget block (audit row + budget_blocks counter)
    curl -X POST http://127.0.0.1:8000/agent/ops.budget \
        -H "Content-Type: application/json" \
        -d '{"intent": "expensive call"}'

    # 4. Query the audit log (from the persistent SQLite store)
    curl -X POST http://127.0.0.1:8000/agent/audit.recent \
        -H "Content-Type: application/json" \
        -d '{"intent": "show recent traces"}'

    curl -X POST http://127.0.0.1:8000/agent/audit.summary \
        -H "Content-Type: application/json" \
        -d '{"intent": "how many traces?"}'

    # 5. Scrape Prometheus metrics
    curl http://127.0.0.1:8000/metrics

    # 6. Standard framework endpoints are still there
    curl http://127.0.0.1:8000/health
    curl http://127.0.0.1:8000/capabilities
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.responses import Response
from starlette.routing import Route

from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.harness.audit import SqliteAuditRecorder
from agenticapi.harness.audit.trace import ExecutionTrace
from agenticapi.observability import (
    configure_metrics,
    configure_tracing,
    is_metrics_available,
)
from agenticapi.observability import metrics as ops_metrics
from agenticapi.observability.tracing import get_tracer
from agenticapi.routing import AgentRouter

if TYPE_CHECKING:
    from starlette.requests import Request

    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# 1. Initialise observability
# ---------------------------------------------------------------------------
# Both calls are idempotent and safe when the OpenTelemetry SDK is not
# installed — the framework falls back to a no-op tracer and no-op
# metric recorders. When the SDK is present, these calls wire up a
# real MeterProvider and TracerProvider with ``service.name = "agenticapi-ops-example"``.

configure_tracing(service_name="agenticapi-ops-example")
configure_metrics(service_name="agenticapi-ops-example", enable_prometheus=True)

tracer = get_tracer()


# ---------------------------------------------------------------------------
# 2. Persistent audit recorder (SQLite, stdlib only)
# ---------------------------------------------------------------------------
# In production you'd point this at a file under ``/var/lib`` or an
# object-store-backed filesystem. For the demo we use a file in the
# example directory so every run appends to the same store — a clean
# way to see that persistence actually works across restarts. The
# test suite overrides the location via an environment variable.

_default_db = Path(__file__).parent / "audit.sqlite"
_audit_path = os.environ.get("AGENTICAPI_OBS_EXAMPLE_DB", str(_default_db))

audit_recorder = SqliteAuditRecorder(path=_audit_path, max_traces=10_000)


# ---------------------------------------------------------------------------
# 3. Manual trace helper
# ---------------------------------------------------------------------------
# The example doesn't go through the full harness pipeline (no LLM,
# no generated code), so handlers construct ``ExecutionTrace`` objects
# by hand to populate the audit store. Real applications that use
# ``HarnessEngine`` get this for free — this helper exists so you can
# see the data model end to end.


async def _record_trace(
    *,
    endpoint: str,
    intent_raw: str,
    intent_action: str = "read",
    error: str | None = None,
    duration_ms: float = 5.0,
    execution_result: Any = None,
) -> str:
    """Construct an ``ExecutionTrace`` and hand it to the recorder.

    Returns the generated trace id so handlers can echo it back to
    the caller.
    """
    trace_id = uuid.uuid4().hex
    trace = ExecutionTrace(
        trace_id=trace_id,
        endpoint_name=endpoint,
        timestamp=datetime.now(tz=UTC),
        intent_raw=intent_raw,
        intent_action=intent_action,
        generated_code="",  # no LLM code generation in this example
        reasoning=None,
        policy_evaluations=[],
        execution_result=execution_result,
        execution_duration_ms=duration_ms,
        error=error,
        llm_usage=None,
        approval_request_id=None,
    )
    await audit_recorder.record(trace)
    return trace_id


# ---------------------------------------------------------------------------
# 4. Application
# ---------------------------------------------------------------------------

app = AgenticApp(
    title="Observability Example",
    version="0.1.0",
    description="Tracing + Prometheus metrics + SQLite audit log",
)


# ---------------------------------------------------------------------------
# 5. Ops endpoints
# ---------------------------------------------------------------------------
# Three endpoints, three outcomes. Each one emits a distinct metric
# pattern so the ``/metrics`` scrape shows a realistic mix of
# counters and histograms after a couple of requests.

ops = AgentRouter(prefix="ops", tags=["ops"])


@ops.agent_endpoint(
    name="ingest",
    description="Happy-path ingest — succeeds and records a request plus LLM usage",
    autonomy_level="auto",
)
async def ops_ingest(intent: Intent, context: AgentContext) -> AgentResponse:
    """Simulate a successful ingest operation.

    Records:
        - ``agenticapi.requests`` counter (endpoint, status=ok)
        - ``agenticapi.request.duration`` histogram
        - ``agenticapi.llm.tokens`` counter (pretend we called an LLM)
        - ``agenticapi.tool.calls`` counter (pretend we hit the DB tool)
        - one persistent audit trace
    """
    with tracer.start_as_current_span("ops.ingest") as span:
        span.set_attribute("agenticapi.endpoint", "ops.ingest")
        span.set_attribute("agenticapi.intent.raw", intent.raw[:120])

        # Pretend-LLM call — record the usage the way a real backend would.
        ops_metrics.record_llm_usage(
            model="gpt-4o-mini",
            input_tokens=180,
            output_tokens=60,
            cost_usd=0.0627,
            latency_seconds=0.231,
        )
        ops_metrics.record_tool_call(tool="database", endpoint="ops.ingest")
        ops_metrics.record_request(
            endpoint="ops.ingest",
            status="ok",
            duration_seconds=0.231,
        )

        trace_id = await _record_trace(
            endpoint="ops.ingest",
            intent_raw=intent.raw,
            intent_action="write",
            duration_ms=231.0,
            execution_result={"documents_ingested": 1},
        )

    return AgentResponse(
        result={
            "ok": True,
            "trace_id": trace_id,
            "documents_ingested": 1,
            "metrics_available": is_metrics_available(),
        },
        reasoning="Recorded one request, one LLM usage, one tool call, one audit trace",
        execution_trace_id=trace_id,
    )


@ops.agent_endpoint(
    name="risky",
    description="Simulated policy denial — bumps policy_denials_total",
    autonomy_level="auto",
)
async def ops_risky(intent: Intent, context: AgentContext) -> AgentResponse:
    """Simulate a policy denial.

    Records:
        - ``agenticapi.policy.denials`` counter (policy=CodePolicy)
        - ``agenticapi.requests`` counter (status=policy_denied)
        - one audit trace with ``error`` populated
    """
    with tracer.start_as_current_span("ops.risky") as span:
        span.set_attribute("agenticapi.endpoint", "ops.risky")
        span.set_attribute("agenticapi.outcome", "policy_denied")

        # In a real app the PolicyEvaluator would raise PolicyViolation
        # and record this counter automatically. We call it directly so
        # the example stays self-contained.
        ops_metrics.record_policy_denial(
            policy="CodePolicy",
            endpoint="ops.risky",
        )
        ops_metrics.record_request(
            endpoint="ops.risky",
            status="policy_denied",
            duration_seconds=0.012,
        )

        trace_id = await _record_trace(
            endpoint="ops.risky",
            intent_raw=intent.raw,
            intent_action="execute",
            error="Policy 'CodePolicy' denied: simulated dangerous import",
            duration_ms=12.0,
        )

    return AgentResponse(
        result={
            "ok": False,
            "trace_id": trace_id,
            "blocked_by": "CodePolicy",
            "reason": "simulated dangerous import",
        },
        status="error",
        reasoning="Policy denial simulated to demonstrate metrics + audit plumbing",
        execution_trace_id=trace_id,
        error="simulated policy violation",
    )


@ops.agent_endpoint(
    name="budget",
    description="Simulated budget block — bumps budget_blocks_total",
    autonomy_level="auto",
)
async def ops_budget(intent: Intent, context: AgentContext) -> AgentResponse:
    """Simulate a BudgetPolicy breach.

    Records:
        - ``agenticapi.budget.blocks`` counter (scope=session)
        - ``agenticapi.requests`` counter (status=budget_exceeded)
        - one audit trace with ``error`` populated
    """
    with tracer.start_as_current_span("ops.budget") as span:
        span.set_attribute("agenticapi.endpoint", "ops.budget")
        span.set_attribute("agenticapi.budget.scope", "session")

        ops_metrics.record_budget_block(scope="session")
        ops_metrics.record_request(
            endpoint="ops.budget",
            status="budget_exceeded",
            duration_seconds=0.008,
        )

        trace_id = await _record_trace(
            endpoint="ops.budget",
            intent_raw=intent.raw,
            intent_action="execute",
            error="Budget exceeded for scope=session: observed $0.4200 > limit $0.3000",
            duration_ms=8.0,
        )

    return AgentResponse(
        result={
            "ok": False,
            "trace_id": trace_id,
            "scope": "session",
            "limit_usd": 0.30,
            "observed_usd": 0.42,
        },
        status="error",
        reasoning="Budget breach simulated to demonstrate budget_blocks counter",
        execution_trace_id=trace_id,
        error="simulated budget exceeded",
    )


# ---------------------------------------------------------------------------
# 6. Audit query endpoints
# ---------------------------------------------------------------------------
# These expose the persistent audit store to an operator UI.

audit = AgentRouter(prefix="audit", tags=["audit"])


@audit.agent_endpoint(
    name="recent",
    description="Return the most recent audit traces",
    autonomy_level="auto",
)
async def audit_recent(intent: Intent, context: AgentContext) -> AgentResponse:
    """List the N most recent audit traces.

    Uses the recorder's synchronous ``get_records`` helper which
    matches the in-memory ``AuditRecorder`` signature so the example
    works against either backend without changes.
    """
    traces = audit_recorder.get_records(limit=20)
    return AgentResponse(
        result={
            "count": len(traces),
            "traces": [
                {
                    "trace_id": t.trace_id,
                    "endpoint": t.endpoint_name,
                    "timestamp": t.timestamp.isoformat(),
                    "intent": t.intent_raw[:120],
                    "error": t.error,
                    "duration_ms": round(t.execution_duration_ms, 1),
                }
                for t in traces
            ],
        },
        reasoning=f"Returned the {len(traces)} most recent SQLite audit rows",
    )


@audit.agent_endpoint(
    name="summary",
    description="Audit-store summary counts (per-endpoint totals)",
    autonomy_level="auto",
)
async def audit_summary(intent: Intent, context: AgentContext) -> AgentResponse:
    """High-level summary of the audit store.

    Returns:
        - total row count via ``SqliteAuditRecorder.count()``
        - per-endpoint breakdown built by walking the last 500 rows
        - a small error sample from the last 500 rows
    """
    total = await audit_recorder.count()
    recent = audit_recorder.get_records(limit=500)
    by_endpoint: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    for trace in recent:
        by_endpoint[trace.endpoint_name] = by_endpoint.get(trace.endpoint_name, 0) + 1
        if trace.error and len(errors) < 5:
            errors.append(
                {
                    "endpoint": trace.endpoint_name,
                    "trace_id": trace.trace_id,
                    "error": trace.error,
                }
            )
    return AgentResponse(
        result={
            "total_traces": total,
            "recent_sample_size": len(recent),
            "by_endpoint": by_endpoint,
            "errors_in_recent": errors,
            "audit_db_path": _audit_path,
        },
        reasoning="Summary built from SqliteAuditRecorder.count() and get_records(500)",
    )


# ---------------------------------------------------------------------------
# 7. Prometheus scrape endpoint
# ---------------------------------------------------------------------------
# A standard ``GET /metrics`` route so any Prometheus server can
# scrape the service. The framework provides the exposition function;
# we just need to wrap it in a Starlette handler and register it via
# ``app.add_routes``.


async def metrics_endpoint(request: Request) -> Response:
    """Return the current Prometheus exposition."""
    body, content_type = ops_metrics.render_prometheus_exposition()
    # When metrics aren't configured (no OTel SDK installed) the
    # helper returns an empty body. Still a valid Prometheus response,
    # and the content type stays correct so scrapers don't choke.
    return Response(content=body, media_type=content_type)


app.add_routes([Route("/metrics", metrics_endpoint, methods=["GET"])])


# ---------------------------------------------------------------------------
# 8. Wire routers
# ---------------------------------------------------------------------------

app.include_router(ops)
app.include_router(audit)
