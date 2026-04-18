"""Trace inspector backend API routes.

Provides JSON endpoints consumed by the trace inspector frontend:

- ``GET /_trace/api/search`` — search traces with filters
- ``GET /_trace/api/traces/{trace_id}`` — single trace detail
- ``GET /_trace/api/diff`` — diff two traces
- ``GET /_trace/api/stats`` — cost analytics
- ``GET /_trace/api/export/{trace_id}`` — compliance export
- ``GET /_trace`` — serve the trace inspector HTML UI
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from starlette.requests import Request

    from agenticapi.app import AgenticApp
    from agenticapi.harness.audit.trace import ExecutionTrace

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _trace_to_summary(trace: ExecutionTrace) -> dict[str, Any]:
    """Convert a trace to a summary dict for search results."""
    cost_usd = 0.0
    if trace.llm_usage:
        usage = trace.llm_usage if isinstance(trace.llm_usage, dict) else {}
        cost_usd = usage.get("cost_usd", 0.0)

    policy_denials = []
    if trace.policy_evaluations:
        evals = trace.policy_evaluations if isinstance(trace.policy_evaluations, list) else []
        for pe in evals:
            if isinstance(pe, dict) and not pe.get("allowed", True):
                policy_denials.append(pe.get("policy", "unknown"))

    status = "success"
    if trace.error:
        status = "error"
    elif policy_denials:
        status = "denied"

    # Extract tool names from stream events and endpoint name.
    tool_names: list[str] = []
    if trace.stream_events:
        events = trace.stream_events if isinstance(trace.stream_events, list) else []
        for ev in events:
            if isinstance(ev, dict):
                data = ev.get("data", {})
                if isinstance(data, dict) and data.get("tool_name"):
                    tool_names.append(data["tool_name"])
    # MCP tool calls use "mcp:{tool_name}" as endpoint_name.
    if trace.endpoint_name and trace.endpoint_name.startswith("mcp:"):
        tool_names.append(trace.endpoint_name.removeprefix("mcp:"))

    return {
        "trace_id": trace.trace_id,
        "endpoint": trace.endpoint_name,
        "timestamp": trace.timestamp.isoformat() if trace.timestamp else "",
        "intent_text": trace.intent_raw or "",
        "intent_action": trace.intent_action or "",
        "status": status,
        "duration_ms": trace.execution_duration_ms or 0,
        "cost_usd": cost_usd,
        "error": trace.error,
        "policy_denials": policy_denials,
        "tools": list(set(tool_names)),
    }


def _trace_to_detail(trace: ExecutionTrace) -> dict[str, Any]:
    """Convert a trace to a full detail dict."""
    summary = _trace_to_summary(trace)

    timeline: list[dict[str, Any]] = []

    if trace.intent_action:
        timeline.append(
            {
                "type": "intent",
                "label": f"Intent: {trace.intent_action}",
                "detail": trace.intent_raw or "",
            }
        )

    if trace.policy_evaluations:
        evals = trace.policy_evaluations if isinstance(trace.policy_evaluations, list) else []
        for pe in evals:
            if isinstance(pe, dict):
                timeline.append(
                    {
                        "type": "policy",
                        "label": f"Policy: {pe.get('policy', '?')}",
                        "detail": "allowed" if pe.get("allowed") else f"denied: {pe.get('violations', [])}",
                        "allowed": pe.get("allowed", True),
                    }
                )

    if trace.generated_code:
        timeline.append(
            {
                "type": "code",
                "label": "Generated code",
                "detail": trace.generated_code,
            }
        )

    if trace.stream_events:
        events = trace.stream_events if isinstance(trace.stream_events, list) else []
        for ev in events:
            if isinstance(ev, dict):
                timeline.append(
                    {
                        "type": "stream_event",
                        "label": ev.get("event_type", "event"),
                        "detail": json.dumps(ev.get("data", {}), default=str),
                    }
                )

    if trace.execution_result is not None:
        timeline.append(
            {
                "type": "result",
                "label": "Execution result",
                "detail": str(trace.execution_result)[:500],
            }
        )

    if trace.error:
        timeline.append(
            {
                "type": "error",
                "label": "Error",
                "detail": trace.error,
            }
        )

    summary["timeline"] = timeline
    summary["generated_code"] = trace.generated_code
    summary["reasoning"] = trace.reasoning
    summary["llm_usage"] = trace.llm_usage if isinstance(trace.llm_usage, dict) else {}
    summary["policy_evaluations"] = trace.policy_evaluations if isinstance(trace.policy_evaluations, list) else []
    summary["stream_events"] = trace.stream_events if isinstance(trace.stream_events, list) else []
    return summary


def _diff_traces(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Compute structural differences between two trace details."""
    changed: list[dict[str, Any]] = []

    # Compare top-level scalar fields.
    for key in ("endpoint", "intent_text", "intent_action", "status", "duration_ms", "cost_usd", "error"):
        va, vb = a.get(key), b.get(key)
        if va != vb:
            changed.append({"field": key, "a": va, "b": vb})

    # Compare generated code.
    if a.get("generated_code") != b.get("generated_code"):
        changed.append({"field": "generated_code", "a": a.get("generated_code"), "b": b.get("generated_code")})

    # Compare policy evaluations.
    if a.get("policy_denials") != b.get("policy_denials"):
        changed.append({"field": "policy_denials", "a": a.get("policy_denials"), "b": b.get("policy_denials")})

    # Compare timeline lengths.
    tl_a = a.get("timeline", [])
    tl_b = b.get("timeline", [])
    if len(tl_a) != len(tl_b):
        changed.append({"field": "timeline_length", "a": len(tl_a), "b": len(tl_b)})

    return {
        "trace_a": a.get("trace_id"),
        "trace_b": b.get("trace_id"),
        "changed": changed,
        "identical": len(changed) == 0,
    }


def _aggregate_stats(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate cost and status statistics from trace summaries."""
    total_cost = 0.0
    by_endpoint: dict[str, float] = {}
    by_status: dict[str, int] = {}
    by_tool: dict[str, int] = {}
    total = len(traces)

    for t in traces:
        cost = t.get("cost_usd", 0.0)
        total_cost += cost
        ep = t.get("endpoint", "unknown")
        by_endpoint[ep] = by_endpoint.get(ep, 0.0) + cost
        st = t.get("status", "unknown")
        by_status[st] = by_status.get(st, 0) + 1
        for tool_name in t.get("tools", []):
            by_tool[tool_name] = by_tool.get(tool_name, 0) + 1

    return {
        "total_traces": total,
        "total_cost_usd": round(total_cost, 6),
        "by_endpoint": by_endpoint,
        "by_status": by_status,
        "by_tool": by_tool,
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


def mount_trace_inspector(app: AgenticApp, url_prefix: str = "/_trace") -> None:
    """Mount trace inspector routes on the given app.

    Args:
        app: The AgenticApp instance.
        url_prefix: URL prefix for the trace inspector.
    """
    api_prefix = f"{url_prefix}/api"

    async def search_handler(request: Request) -> Response:
        """Search traces with filters."""
        if app._harness is None:
            return JSONResponse({"traces": [], "total": 0})

        recorder = app._harness.audit_recorder
        endpoint = request.query_params.get("endpoint")
        limit = min(int(request.query_params.get("limit", "100")), 1000)

        records = recorder.get_records(endpoint_name=endpoint, limit=limit)
        summaries = [_trace_to_summary(r) for r in records]

        # Apply client-side filters that the recorder doesn't support.
        status_filter = request.query_params.get("status")
        if status_filter:
            summaries = [s for s in summaries if s["status"] == status_filter]

        policy_filter = request.query_params.get("policy")
        if policy_filter:
            summaries = [s for s in summaries if policy_filter in s.get("policy_denials", [])]

        from_date = request.query_params.get("from")
        if from_date:
            summaries = [s for s in summaries if s.get("timestamp", "") >= from_date]

        to_date = request.query_params.get("to")
        if to_date:
            summaries = [s for s in summaries if s.get("timestamp", "") <= to_date]

        min_cost = request.query_params.get("min_cost")
        if min_cost:
            summaries = [s for s in summaries if s.get("cost_usd", 0) >= float(min_cost)]

        max_cost = request.query_params.get("max_cost")
        if max_cost:
            summaries = [s for s in summaries if s.get("cost_usd", 0) <= float(max_cost)]

        tool_filter = request.query_params.get("tool")
        if tool_filter:
            summaries = [s for s in summaries if tool_filter in s.get("tools", [])]

        offset = int(request.query_params.get("offset", "0"))
        page_limit = int(request.query_params.get("page_limit", str(len(summaries))))
        total = len(summaries)
        summaries = summaries[offset : offset + page_limit]

        return JSONResponse({"traces": summaries, "total": total})

    async def trace_detail_handler(request: Request) -> Response:
        """Get full trace detail by ID."""
        trace_id = request.path_params["trace_id"]
        if app._harness is None:
            return JSONResponse({"error": "No harness configured"}, status_code=404)

        recorder = app._harness.audit_recorder
        trace = recorder.get_by_id(trace_id)
        if trace is None:
            return JSONResponse({"error": "Trace not found"}, status_code=404)

        return JSONResponse(_trace_to_detail(trace))

    async def diff_handler(request: Request) -> Response:
        """Diff two traces."""
        trace_a_id = request.query_params.get("a")
        trace_b_id = request.query_params.get("b")
        if not trace_a_id or not trace_b_id:
            return JSONResponse({"error": "Both 'a' and 'b' trace IDs required"}, status_code=400)

        if app._harness is None:
            return JSONResponse({"error": "No harness configured"}, status_code=404)

        recorder = app._harness.audit_recorder
        ta = recorder.get_by_id(trace_a_id)
        tb = recorder.get_by_id(trace_b_id)
        if ta is None or tb is None:
            missing = trace_a_id if ta is None else trace_b_id
            return JSONResponse({"error": f"Trace {missing} not found"}, status_code=404)

        detail_a = _trace_to_detail(ta)
        detail_b = _trace_to_detail(tb)
        return JSONResponse(_diff_traces(detail_a, detail_b))

    async def stats_handler(request: Request) -> Response:
        """Aggregate stats across traces."""
        if app._harness is None:
            return JSONResponse(_aggregate_stats([]))

        recorder = app._harness.audit_recorder
        endpoint = request.query_params.get("endpoint")
        limit = min(int(request.query_params.get("limit", "500")), 5000)
        records = recorder.get_records(endpoint_name=endpoint, limit=limit)
        summaries = [_trace_to_summary(r) for r in records]
        return JSONResponse(_aggregate_stats(summaries))

    async def export_handler(request: Request) -> Response:
        """Export a trace as a JSON compliance report."""
        trace_id = request.path_params["trace_id"]
        if app._harness is None:
            return JSONResponse({"error": "No harness configured"}, status_code=404)

        recorder = app._harness.audit_recorder
        trace = recorder.get_by_id(trace_id)
        if trace is None:
            return JSONResponse({"error": "Trace not found"}, status_code=404)

        detail = _trace_to_detail(trace)
        report = {
            "report_type": "agenticapi_trace_export",
            "exported_at": datetime.now(tz=UTC).isoformat(),
            "trace": detail,
        }
        content = json.dumps(report, indent=2, default=str)
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="trace_{trace_id}.json"',
            },
        )

    async def inspector_handler(request: Request) -> Response:
        """Serve the trace inspector HTML UI."""
        return HTMLResponse(_build_inspector_html(api_prefix))

    app._trace_inspector_routes = [
        Route(f"{api_prefix}/search", search_handler, methods=["GET"]),
        Route(f"{api_prefix}/traces/{{trace_id}}", trace_detail_handler, methods=["GET"]),
        Route(f"{api_prefix}/diff", diff_handler, methods=["GET"]),
        Route(f"{api_prefix}/stats", stats_handler, methods=["GET"]),
        Route(f"{api_prefix}/export/{{trace_id}}", export_handler, methods=["GET"]),
        Route(url_prefix, inspector_handler, methods=["GET"]),
    ]


def _build_inspector_html(api_prefix: str) -> str:
    """Build the self-contained trace inspector HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgenticAPI Trace Inspector</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
         background: #0d1117; color: #c9d1d9; }}
  .header {{ background: #161b22; border-bottom: 1px solid #30363d; padding: 12px 20px;
             display: flex; align-items: center; gap: 16px; }}
  .header h1 {{ font-size: 18px; color: #58a6ff; }}
  .tabs {{ display: flex; gap: 4px; }}
  .tab {{ padding: 6px 16px; background: #21262d; border: 1px solid #30363d;
          border-radius: 6px; cursor: pointer; color: #8b949e; font-size: 13px; }}
  .tab.active {{ background: #1f6feb; color: #fff; border-color: #1f6feb; }}
  .content {{ padding: 16px 20px; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
  .filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
  .filters input, .filters select {{ padding: 6px 10px; background: #21262d; border: 1px solid #30363d;
    border-radius: 4px; color: #c9d1d9; font-size: 13px; }}
  .filters button {{ padding: 6px 14px; background: #238636; border: none; border-radius: 4px;
    color: #fff; cursor: pointer; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 8px 10px; background: #161b22; border-bottom: 1px solid #30363d;
       color: #8b949e; font-weight: 600; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #21262d; }}
  tr:hover {{ background: #161b22; }}
  .badge {{ padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .badge.success {{ background: #238636; color: #fff; }}
  .badge.error {{ background: #da3633; color: #fff; }}
  .badge.denied {{ background: #d29922; color: #000; }}
  .detail-panel {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 16px; margin-top: 12px; }}
  .timeline-entry {{ padding: 8px 12px; border-left: 3px solid #30363d; margin-bottom: 8px; }}
  .timeline-entry.policy {{ border-color: #d29922; }}
  .timeline-entry.error {{ border-color: #da3633; }}
  .timeline-entry.result {{ border-color: #238636; }}
  .diff-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 8px; }}
  .diff-cell {{ padding: 8px; background: #21262d; border-radius: 4px; font-size: 13px;
    word-break: break-all; }}
  .diff-cell.changed {{ border: 1px solid #d29922; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
  .stat-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
  .stat-value {{ font-size: 28px; font-weight: 700; color: #58a6ff; }}
  .stat-label {{ font-size: 12px; color: #8b949e; margin-top: 4px; }}
  .clickable {{ cursor: pointer; color: #58a6ff; text-decoration: underline; }}
  pre {{ background: #0d1117; padding: 8px; border-radius: 4px; overflow-x: auto;
    font-size: 12px; white-space: pre-wrap; }}
  .export-btn {{ display: inline-block; padding: 6px 14px; background: #21262d;
    border: 1px solid #30363d; border-radius: 4px; color: #58a6ff; cursor: pointer;
    text-decoration: none; font-size: 13px; margin-top: 8px; }}
</style>
</head>
<body>
<div class="header">
  <h1>Trace Inspector</h1>
  <div class="tabs">
    <div class="tab active" onclick="showTab('search')">Search</div>
    <div class="tab" onclick="showTab('detail')">Detail</div>
    <div class="tab" onclick="showTab('diff')">Diff</div>
    <div class="tab" onclick="showTab('stats')">Stats</div>
  </div>
</div>
<div class="content">
  <!-- SEARCH TAB -->
  <div id="tab-search" class="panel active">
    <div class="filters">
      <input id="f-endpoint" placeholder="Endpoint" />
      <select id="f-status">
        <option value="">Any status</option>
        <option value="success">Success</option>
        <option value="error">Error</option>
        <option value="denied">Denied</option>
      </select>
      <input id="f-tool" placeholder="Tool name" />
      <input id="f-from" type="date" title="From date" />
      <input id="f-to" type="date" title="To date" />
      <button onclick="doSearch()">Search</button>
    </div>
    <table>
      <thead><tr><th>Trace ID</th><th>Endpoint</th><th>Status</th>
      <th>Duration</th><th>Cost</th><th>Time</th></tr></thead>
      <tbody id="search-results"></tbody>
    </table>
  </div>
  <!-- DETAIL TAB -->
  <div id="tab-detail" class="panel">
    <div id="detail-content"><p style="color:#8b949e">Click a trace ID from search results.</p></div>
  </div>
  <!-- DIFF TAB -->
  <div id="tab-diff" class="panel">
    <div class="filters">
      <input id="d-a" placeholder="Trace A ID" />
      <input id="d-b" placeholder="Trace B ID" />
      <button onclick="doDiff()">Compare</button>
    </div>
    <div id="diff-content"></div>
  </div>
  <!-- STATS TAB -->
  <div id="tab-stats" class="panel">
    <div class="filters">
      <input id="s-endpoint" placeholder="Endpoint (optional)" />
      <button onclick="doStats()">Refresh</button>
    </div>
    <div id="stats-content" class="stat-grid"></div>
  </div>
</div>
<script>
const API = '{api_prefix}';

function esc(s) {{
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}}

function showTab(name) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.querySelectorAll('.tab').forEach(t => {{
    if (t.textContent.toLowerCase() === name) t.classList.add('active');
  }});
}}

async function doSearch() {{
  const params = new URLSearchParams();
  const ep = document.getElementById('f-endpoint').value;
  const st = document.getElementById('f-status').value;
  const fr = document.getElementById('f-from').value;
  const to = document.getElementById('f-to').value;
  const tl = document.getElementById('f-tool').value;
  if (ep) params.set('endpoint', ep);
  if (st) params.set('status', st);
  if (tl) params.set('tool', tl);
  if (fr) params.set('from', fr);
  if (to) params.set('to', to);
  const r = await fetch(API + '/search?' + params);
  const data = await r.json();
  const tbody = document.getElementById('search-results');
  tbody.innerHTML = data.traces.map(t => `<tr>
    <td class="clickable" onclick="loadTrace('${{esc(t.trace_id)}}')">
      ${{esc(t.trace_id.substring(0,12))}}...</td>
    <td>${{esc(t.endpoint || '-')}}</td>
    <td><span class="badge ${{t.status}}">${{esc(t.status)}}</span></td>
    <td>${{t.duration_ms ? t.duration_ms.toFixed(1) + 'ms' : '-'}}</td>
    <td>${{t.cost_usd ? '$' + t.cost_usd.toFixed(4) : '-'}}</td>
    <td>${{t.timestamp ? esc(new Date(t.timestamp).toLocaleString()) : '-'}}</td>
  </tr>`).join('');
}}

async function loadTrace(id) {{
  const r = await fetch(API + '/traces/' + id);
  if (!r.ok) {{ document.getElementById('detail-content').innerHTML = '<p>Trace not found</p>'; return; }}
  const t = await r.json();
  let html = `<div class="detail-panel">
    <h3>Trace ${{esc(t.trace_id)}}</h3>
    <p><strong>Endpoint:</strong> ${{esc(t.endpoint)}} |
    <strong>Status:</strong>
    <span class="badge ${{t.status}}">${{esc(t.status)}}</span> |
    <strong>Duration:</strong> ${{t.duration_ms?.toFixed(1) || 0}}ms |
    <strong>Cost:</strong> $${{t.cost_usd?.toFixed(4) || '0.0000'}}</p>
    <a class="export-btn" href="${{API}}/export/${{esc(t.trace_id)}}"
       download>Export JSON</a>
    <h4 style="margin-top:16px;margin-bottom:8px;color:#8b949e">
      Timeline</h4>`;
  (t.timeline || []).forEach(e => {{
    html += `<div class="timeline-entry ${{esc(e.type)}}">
      <strong>${{esc(e.label)}}</strong><br>
      <pre>${{esc(e.detail)}}</pre></div>`;
  }});
  if (t.llm_usage && Object.keys(t.llm_usage).length) {{
    const u = esc(JSON.stringify(t.llm_usage, null, 2));
    html += `<h4 style="margin-top:16px;color:#8b949e">LLM Usage</h4>
      <pre>${{u}}</pre>`;
  }}
  html += '</div>';
  document.getElementById('detail-content').innerHTML = html;
  showTab('detail');
}}

async function doDiff() {{
  const a = document.getElementById('d-a').value;
  const b = document.getElementById('d-b').value;
  if (!a || !b) return;
  const r = await fetch(API + '/diff?a=' + a + '&b=' + b);
  const d = await r.json();
  if (d.error) {{ document.getElementById('diff-content').innerHTML = `<p>${{esc(d.error)}}</p>`; return; }}
  let html = d.identical ? '<p style="color:#238636">Traces are identical.</p>' : '';
  (d.changed || []).forEach(c => {{
    html += `<div class="diff-row">
      <div class="diff-cell changed"><strong>${{esc(c.field)}}</strong><br>${{esc(JSON.stringify(c.a))}}</div>
      <div class="diff-cell changed"><strong>${{esc(c.field)}}</strong><br>${{esc(JSON.stringify(c.b))}}</div>
    </div>`;
  }});
  document.getElementById('diff-content').innerHTML = html;
}}

async function doStats() {{
  const ep = document.getElementById('s-endpoint').value;
  const params = ep ? '?endpoint=' + ep : '';
  const r = await fetch(API + '/stats' + params);
  const s = await r.json();
  const sc = (l,v) => `<div class="stat-card"><div class="stat-value">${{v}}</div>`
    + `<div class="stat-label">${{l}}</div></div>`;
  let html = sc('Total Traces', s.total_traces)
    + sc('Total Cost', '$$' + s.total_cost_usd.toFixed(4));
  Object.entries(s.by_status || {{}}).forEach(([k,v]) => {{
    html += sc(k, v);
  }});
  Object.entries(s.by_endpoint || {{}}).forEach(([k,v]) => {{
    html += sc(k, '$$' + v.toFixed(4));
  }});
  document.getElementById('stats-content').innerHTML = html;
}}

// Auto-load search on page load.
doSearch();
</script>
</body>
</html>"""
