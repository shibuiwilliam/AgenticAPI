"""Playground backend API routes.

Provides JSON endpoints consumed by the playground frontend:

- ``GET /_playground/api/endpoints`` — registered agent endpoints
- ``GET /_playground/api/traces`` — recent execution traces
- ``GET /_playground/api/traces/{trace_id}`` — single trace detail
- ``POST /_playground/api/chat`` — proxy to an agent endpoint (SSE)
- ``GET /_playground`` — serve the playground HTML UI
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from starlette.requests import Request

    from agenticapi.app import AgenticApp

logger = structlog.get_logger(__name__)


def _get_endpoints(app: AgenticApp) -> list[dict[str, Any]]:
    """Build endpoint metadata for the playground."""
    endpoints = []
    for name, ep in app._endpoints.items():
        tools_list: list[str] = []
        if app._tools is not None:
            tools_list = [t.name for t in app._tools.get_definitions()]

        policies_list: list[str] = []
        if app._harness is not None:
            policies_list = [type(p).__name__ for p in app._harness._evaluator.policies]

        loop_config_dict: dict[str, Any] | None = None
        if ep.loop_config is not None:
            loop_config_dict = {
                "max_iterations": ep.loop_config.max_iterations,
            }

        endpoints.append(
            {
                "name": name,
                "path": f"/agent/{name}",
                "description": ep.description,
                "tools": tools_list,
                "policies": policies_list,
                "has_workflow": False,
                "loop_config": loop_config_dict,
                "auth_required": ep.auth is not None,
                "streaming": ep.streaming,
            }
        )
    return endpoints


def _get_traces(app: AgenticApp, since: str | None, limit: int, endpoint: str | None) -> list[dict[str, Any]]:
    """Fetch recent traces from the audit recorder."""
    if app._harness is None:
        return []

    recorder = app._harness.audit_recorder
    records = recorder.get_records(endpoint_name=endpoint, limit=limit)

    traces = []
    for r in records:
        traces.append(
            {
                "trace_id": r.trace_id,
                "endpoint": r.endpoint_name,
                "timestamp": r.timestamp.isoformat() if r.timestamp else "",
                "intent_text": r.intent_raw,
                "status": "error" if r.error else "success",
                "duration_ms": r.execution_duration_ms,
                "cost_usd": 0.0,
                "error": r.error,
            }
        )
    return traces


def _get_trace_detail(app: AgenticApp, trace_id: str) -> dict[str, Any] | None:
    """Fetch a single trace with full timeline."""
    if app._harness is None:
        return None

    recorder = app._harness.audit_recorder
    trace = recorder.get_by_id(trace_id)
    if trace is None:
        return None

    timeline: list[dict[str, Any]] = []
    if trace.intent_action:
        timeline.append(
            {
                "type": "intent_parsed",
                "ts": trace.timestamp.isoformat() if trace.timestamp else "",
                "action": trace.intent_action,
            }
        )

    for pe in trace.policy_evaluations:
        timeline.append(
            {
                "type": "policy_eval",
                "ts": trace.timestamp.isoformat() if trace.timestamp else "",
                "policy": pe.get("policy", ""),
                "result": pe.get("result", ""),
            }
        )

    if trace.generated_code:
        timeline.append(
            {
                "type": "tool_call",
                "ts": trace.timestamp.isoformat() if trace.timestamp else "",
                "detail": trace.generated_code[:200],
            }
        )

    for se in trace.stream_events:
        timeline.append(
            {
                "type": f"stream_{se.get('kind', 'unknown')}",
                "ts": se.get("timestamp", ""),
                "detail": se,
            }
        )

    timeline.append(
        {
            "type": "response",
            "ts": trace.timestamp.isoformat() if trace.timestamp else "",
            "duration_ms": trace.execution_duration_ms,
            "has_error": trace.error is not None,
        }
    )

    return {
        "trace_id": trace.trace_id,
        "endpoint": trace.endpoint_name,
        "timestamp": trace.timestamp.isoformat() if trace.timestamp else "",
        "intent_raw": trace.intent_raw,
        "intent_action": trace.intent_action,
        "generated_code": trace.generated_code,
        "reasoning": trace.reasoning,
        "execution_result": str(trace.execution_result)[:500] if trace.execution_result else None,
        "duration_ms": trace.execution_duration_ms,
        "error": trace.error,
        "timeline": timeline,
    }


def _build_playground_html() -> str:
    """Build the playground HTML page."""
    return _PLAYGROUND_HTML


def mount_playground(app: AgenticApp, url_prefix: str = "/_playground") -> None:
    """Mount playground routes on the app.

    Call this from ``AgenticApp.__init__`` when ``playground_url``
    is set. The playground is disabled by default in production.

    Args:
        app: The AgenticApp instance.
        url_prefix: The URL prefix for playground routes.
    """
    api_prefix = f"{url_prefix}/api"

    async def endpoints_handler(request: Request) -> Response:
        return JSONResponse(_get_endpoints(app))

    async def traces_handler(request: Request) -> Response:
        since = request.query_params.get("since")
        limit = int(request.query_params.get("limit", "50"))
        endpoint = request.query_params.get("endpoint")
        return JSONResponse(_get_traces(app, since, limit, endpoint))

    async def trace_detail_handler(request: Request) -> Response:
        trace_id = request.path_params["trace_id"]
        detail = _get_trace_detail(app, trace_id)
        if detail is None:
            return JSONResponse({"error": "Trace not found"}, status_code=404)
        return JSONResponse(detail)

    async def chat_handler(request: Request) -> Response:
        body = await request.json()
        endpoint_name = body.get("endpoint", "")
        message = body.get("message", "")

        if endpoint_name not in app._endpoints:
            return JSONResponse({"error": f"Unknown endpoint: {endpoint_name}"}, status_code=404)

        # Dispatch through the app's process_intent() method directly.
        try:
            from agenticapi.interface.response import AgentResponse

            response = await app.process_intent(
                endpoint_name=endpoint_name,
                raw_request=message,
            )
            if isinstance(response, AgentResponse):
                return JSONResponse(response.to_dict())
            # Raw Starlette Response (e.g. FileResult) — pass through.
            return response
        except Exception as exc:
            logger.error("playground_chat_error", endpoint=endpoint_name, error=str(exc))
            return JSONResponse({"error": str(exc)}, status_code=500)

    async def playground_handler(request: Request) -> Response:
        return HTMLResponse(_build_playground_html())

    # Store routes for later mounting.
    app._playground_routes = [
        Route(f"{api_prefix}/endpoints", endpoints_handler, methods=["GET"]),
        Route(f"{api_prefix}/traces", traces_handler, methods=["GET"]),
        Route(f"{api_prefix}/traces/{{trace_id}}", trace_detail_handler, methods=["GET"]),
        Route(f"{api_prefix}/chat", chat_handler, methods=["POST"]),
        Route(url_prefix, playground_handler, methods=["GET"]),
    ]

    logger.info("playground_mounted", url=url_prefix)


# ---------------------------------------------------------------------------
# Inline HTML template (no external dependencies)
# ---------------------------------------------------------------------------

_PLAYGROUND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AgenticAPI Playground</title>
<style>
:root {
  --bg: #1a1b26; --surface: #24283b; --border: #3b4261;
  --text: #c0caf5; --muted: #565f89; --accent: #7aa2f7;
  --green: #9ece6a; --red: #f7768e; --yellow: #e0af68;
  --blue: #7aa2f7; --purple: #bb9af7;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'SF Mono','Fira Code',monospace; background:var(--bg);
       color:var(--text); font-size:13px; height:100vh; display:flex; flex-direction:column; }
header { background:var(--surface); border-bottom:1px solid var(--border);
         padding:12px 20px; display:flex; align-items:center; gap:16px; }
header h1 { font-size:16px; color:var(--accent); font-weight:600; }
header .badge { background:var(--accent); color:var(--bg); padding:2px 8px;
                border-radius:3px; font-size:11px; font-weight:600; }
.panels { display:flex; flex:1; overflow:hidden; }
.panel { flex:1; border-right:1px solid var(--border); display:flex;
         flex-direction:column; overflow:hidden; }
.panel:last-child { border-right:none; }
.panel-header { background:var(--surface); padding:8px 12px;
                border-bottom:1px solid var(--border); font-weight:600;
                font-size:12px; color:var(--muted); text-transform:uppercase;
                letter-spacing:0.5px; }
.panel-body { flex:1; overflow-y:auto; padding:12px; }

/* Chat panel */
#chat-messages { display:flex; flex-direction:column; gap:8px; }
.msg { padding:8px 12px; border-radius:6px; max-width:90%; word-wrap:break-word; }
.msg.user { background:var(--accent); color:var(--bg); align-self:flex-end; }
.msg.agent { background:var(--surface); border:1px solid var(--border); align-self:flex-start; }
.msg.tool { background:#1e2030; border-left:3px solid var(--purple); font-size:12px; }
.msg.thought { background:#1e2030; border-left:3px solid var(--yellow); font-style:italic; font-size:12px; }

#chat-input { display:flex; gap:8px; padding:12px; border-top:1px solid var(--border); }
#chat-input select { background:var(--surface); color:var(--text); border:1px solid var(--border);
                     padding:6px 8px; border-radius:4px; font-size:12px; }
#chat-input input { flex:1; background:var(--surface); color:var(--text);
                    border:1px solid var(--border); padding:8px 12px; border-radius:4px;
                    font-family:inherit; font-size:13px; }
#chat-input button { background:var(--accent); color:var(--bg); border:none;
                     padding:8px 16px; border-radius:4px; cursor:pointer;
                     font-weight:600; font-size:13px; }
#chat-input button:hover { opacity:0.9; }

/* Trace panel */
.trace-item { padding:8px; border-bottom:1px solid var(--border); cursor:pointer; }
.trace-item:hover { background:var(--surface); }
.trace-item .status { display:inline-block; width:8px; height:8px;
                      border-radius:50%; margin-right:6px; }
.trace-item .status.success { background:var(--green); }
.trace-item .status.error { background:var(--red); }
.trace-item .meta { font-size:11px; color:var(--muted); margin-top:2px; }

/* Timeline */
.timeline-entry { padding:6px 8px; border-left:3px solid var(--border);
                  margin-left:8px; margin-bottom:4px; font-size:12px; }
.timeline-entry.policy_eval { border-color:var(--green); }
.timeline-entry.tool_call { border-color:var(--purple); }
.timeline-entry.response { border-color:var(--blue); }
.timeline-entry.error { border-color:var(--red); }
.timeline-entry .type { font-weight:600; color:var(--muted); text-transform:uppercase;
                        font-size:10px; letter-spacing:0.5px; }
.timeline-entry .detail { margin-top:2px; }

.empty-state { text-align:center; color:var(--muted); padding:40px 20px; }
.empty-state p { margin-top:8px; font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>AgenticAPI Playground</h1>
  <span class="badge">DEV</span>
</header>
<div class="panels">
  <!-- Chat Panel -->
  <div class="panel">
    <div class="panel-header">Agent Chat</div>
    <div class="panel-body" id="chat-messages">
      <div class="empty-state">
        <p>Select an endpoint and type a message to start.</p>
      </div>
    </div>
    <div id="chat-input">
      <select id="endpoint-select"><option value="">Loading...</option></select>
      <input id="message-input" type="text" placeholder="Type your intent..." />
      <button id="send-btn" onclick="sendMessage()">Send</button>
    </div>
  </div>

  <!-- Trace Viewer Panel -->
  <div class="panel">
    <div class="panel-header">Execution Trace</div>
    <div class="panel-body" id="trace-viewer">
      <div class="empty-state">
        <p>Send a message or click a trace to view details.</p>
      </div>
    </div>
  </div>

  <!-- Trace History Panel -->
  <div class="panel">
    <div class="panel-header">Trace History</div>
    <div class="panel-body" id="trace-history">
      <div class="empty-state">
        <p>No traces yet.</p>
      </div>
    </div>
  </div>
</div>

<script>
const API = '/_playground/api';
let endpoints = [];

async function loadEndpoints() {
  try {
    const r = await fetch(API + '/endpoints');
    endpoints = await r.json();
    const sel = document.getElementById('endpoint-select');
    sel.innerHTML = endpoints.map(e =>
      '<option value="' + e.name + '">' + e.name + '</option>'
    ).join('');
  } catch(e) { console.error('Failed to load endpoints:', e); }
}

async function loadTraces() {
  try {
    const r = await fetch(API + '/traces?limit=20');
    const traces = await r.json();
    const el = document.getElementById('trace-history');
    if (!traces.length) {
      el.innerHTML = '<div class="empty-state"><p>No traces yet.</p></div>';
      return;
    }
    el.innerHTML = traces.map(t => `
      <div class="trace-item" onclick="loadTrace('${t.trace_id}')">
        <span class="status ${t.status}"></span>
        <strong>${t.endpoint}</strong>
        <div class="meta">${t.intent_text.substring(0,60)} &mdash; ${Math.round(t.duration_ms)}ms</div>
      </div>
    `).join('');
  } catch(e) { console.error('Failed to load traces:', e); }
}

async function loadTrace(traceId) {
  try {
    const r = await fetch(API + '/traces/' + traceId);
    const detail = await r.json();
    const el = document.getElementById('trace-viewer');
    el.innerHTML = `
      <div style="margin-bottom:12px">
        <strong>${detail.endpoint}</strong>
        <span style="color:var(--muted);font-size:11px;margin-left:8px">${detail.trace_id.substring(0,8)}</span>
        <div style="color:var(--muted);font-size:11px;margin-top:2px">${detail.intent_raw}</div>
      </div>
      ${detail.timeline.map(t => `
        <div class="timeline-entry ${t.type}">
          <div class="type">${t.type}</div>
          <div class="detail">${JSON.stringify(t).substring(0,200)}</div>
        </div>
      `).join('')}
    `;
  } catch(e) { console.error('Failed to load trace:', e); }
}

async function sendMessage() {
  const endpoint = document.getElementById('endpoint-select').value;
  const input = document.getElementById('message-input');
  const message = input.value.trim();
  if (!endpoint || !message) return;

  const chatEl = document.getElementById('chat-messages');
  // Clear empty state
  if (chatEl.querySelector('.empty-state')) chatEl.innerHTML = '';

  // Add user message
  chatEl.innerHTML += '<div class="msg user">' + escapeHtml(message) + '</div>';
  input.value = '';

  try {
    const r = await fetch(API + '/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({endpoint, message})
    });
    const data = await r.json();
    const result = data.result || data.error || JSON.stringify(data);
    const resultStr = typeof result === 'object' ? JSON.stringify(result, null, 2) : String(result);
    chatEl.innerHTML += '<div class="msg agent">' + escapeHtml(resultStr) + '</div>';
    chatEl.scrollTop = chatEl.scrollHeight;

    // Refresh traces
    setTimeout(loadTraces, 500);
  } catch(e) {
    chatEl.innerHTML += '<div class="msg agent" style="border-color:var(--red)">Error: ' + e.message + '</div>';
  }
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

document.getElementById('message-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendMessage();
});

loadEndpoints();
loadTraces();
</script>
</body>
</html>"""
