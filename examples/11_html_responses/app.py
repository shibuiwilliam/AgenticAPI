"""HTML and custom response example.

Demonstrates:
- HTMLResult for returning HTML pages from agent endpoints
- PlainTextResult for plain text responses
- FileResult with text/html media type for HTML file downloads
- Direct Starlette Response passthrough (HTMLResponse, StreamingResponse)
- Mixed endpoints: some return JSON (default), others return HTML or text

Run with:
    uvicorn examples.11_html_responses.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.11_html_responses.app:app

Test with curl:
    # HTML page
    curl -X POST http://127.0.0.1:8000/agent/pages.home \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show the home page"}'

    # Dynamic HTML based on intent
    curl -X POST http://127.0.0.1:8000/agent/pages.search \
        -H "Content-Type: application/json" \
        -d '{"intent": "Search for Python tutorials"}'

    # Plain text status
    curl -X POST http://127.0.0.1:8000/agent/pages.status \
        -H "Content-Type: application/json" \
        -d '{"intent": "Check system status"}'

    # HTML report download
    curl -X POST http://127.0.0.1:8000/agent/pages.report \
        -H "Content-Type: application/json" \
        -d '{"intent": "Generate a report"}' -o report.html

    # JSON endpoint (standard AgentResponse)
    curl -X POST http://127.0.0.1:8000/agent/pages.api \
        -H "Content-Type: application/json" \
        -d '{"intent": "Get API data"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agenticapi import AgenticApp, Intent
from agenticapi.interface.response import FileResult, HTMLResult, PlainTextResult
from agenticapi.routing import AgentRouter

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_BASE_CSS = """\
body { font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }
h1 { color: #4f46e5; }
.card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }
.ok { background: #dcfce7; color: #166534; }
.info { background: #dbeafe; color: #1e40af; }
"""


def _page(title: str, body: str) -> str:
    """Wrap content in a minimal HTML page."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title><style>{_BASE_CSS}</style></head>
<body>{body}</body>
</html>"""


# ---------------------------------------------------------------------------
# Router and endpoints
# ---------------------------------------------------------------------------

app = AgenticApp(title="HTML Response Example", version="0.1.0")
pages = AgentRouter(prefix="pages", tags=["pages"])


@pages.agent_endpoint(
    name="home",
    description="Render the home page as HTML",
    autonomy_level="auto",
)
async def home_page(intent: Intent, context: AgentContext) -> HTMLResult:
    """Return a static HTML home page."""
    body = """\
<h1>Welcome to AgenticAPI</h1>
<p>This page is returned as <code>text/html</code> from an agent endpoint.</p>
<div class="card">
    <h3>How it works</h3>
    <p>The handler returns <code>HTMLResult(content="...")</code> and the framework
       serves it directly without JSON wrapping.</p>
</div>"""
    return HTMLResult(content=_page("Home", body))


@pages.agent_endpoint(
    name="search",
    description="Search and render results as an HTML page",
    autonomy_level="auto",
)
async def search_page(intent: Intent, context: AgentContext) -> HTMLResult:
    """Dynamic HTML based on the user's intent."""
    query = intent.raw
    # Simulate search results
    results = [
        {"title": "Getting Started with Python", "url": "#", "snippet": "Learn Python basics..."},
        {"title": "Advanced Python Patterns", "url": "#", "snippet": "Design patterns in Python..."},
        {"title": "Python Web Frameworks", "url": "#", "snippet": "FastAPI, Django, AgenticAPI..."},
    ]

    items_html = ""
    for r in results:
        items_html += f"""\
<div class="card">
    <h3><a href="{r["url"]}">{r["title"]}</a></h3>
    <p>{r["snippet"]}</p>
</div>"""

    body = f"""\
<h1>Search Results</h1>
<p>Query: <strong>{query}</strong></p>
<p><span class="badge info">{len(results)} results</span></p>
{items_html}"""

    return HTMLResult(content=_page(f"Search: {query}", body))


@pages.agent_endpoint(
    name="status",
    description="Return system status as plain text",
    autonomy_level="auto",
)
async def status_text(intent: Intent, context: AgentContext) -> PlainTextResult:
    """Return plain text status."""
    lines = [
        "AgenticAPI Status Report",
        "========================",
        "Endpoint: pages.status",
        f"Intent: {intent.raw}",
        f"Session: {context.session_id or 'none'}",
        "Status: OK",
    ]
    return PlainTextResult(content="\n".join(lines))


@pages.agent_endpoint(
    name="report",
    description="Generate an HTML report as a downloadable file",
    autonomy_level="auto",
)
async def html_report(intent: Intent, context: AgentContext) -> FileResult:
    """Return an HTML file for download (Content-Disposition: attachment)."""
    body = f"""\
<h1>Report</h1>
<p>Generated for: <strong>{intent.raw}</strong></p>
<table border="1" cellpadding="8" style="border-collapse: collapse;">
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Total Requests</td><td>1,234</td></tr>
    <tr><td>Avg Response Time</td><td>45ms</td></tr>
    <tr><td>Error Rate</td><td>0.3%</td></tr>
</table>"""

    return FileResult(
        content=_page("Report", body).encode("utf-8"),
        media_type="text/html",
        filename="report.html",
    )


@pages.agent_endpoint(
    name="api",
    description="Standard JSON API endpoint (for comparison)",
    autonomy_level="auto",
)
async def json_api(intent: Intent, context: AgentContext) -> dict[str, object]:
    """Standard JSON response for comparison with HTML endpoints."""
    return {
        "message": f"You asked: {intent.raw}",
        "format": "json",
        "endpoints": {
            "pages.home": "Returns HTML",
            "pages.search": "Returns HTML with search results",
            "pages.status": "Returns plain text",
            "pages.report": "Returns downloadable HTML file",
            "pages.api": "Returns JSON (this endpoint)",
        },
    }


app.include_router(pages)
