"""HTMX example: interactive web app with partial page updates.

Demonstrates:
- HtmxHeaders for detecting HTMX requests vs. full-page loads
- HTMLResult for returning HTML fragments and full pages
- htmx_response_headers for controlling client-side swap behavior
- Full page on first load, fragments on HTMX requests
- Form submission with HTMX (search, add items)

Prerequisites:
    No LLM or API key needed.

Run with:
    uvicorn examples.12_htmx.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.12_htmx.app:app

Test with curl:
    # Full HTML page (non-HTMX)
    curl -X POST http://127.0.0.1:8000/agent/todo.list \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show my todo list"}'

    # HTMX fragment (partial update)
    curl -X POST http://127.0.0.1:8000/agent/todo.list \
        -H "Content-Type: application/json" \
        -H "HX-Request: true" \
        -d '{"intent": "Show my todo list"}'

    # Add item (returns fragment + HX-Trigger header)
    curl -X POST http://127.0.0.1:8000/agent/todo.add \
        -H "Content-Type: application/json" \
        -H "HX-Request: true" \
        -d '{"intent": "Buy groceries"}'

    # Search (returns filtered fragment)
    curl -X POST http://127.0.0.1:8000/agent/todo.search \
        -H "Content-Type: application/json" \
        -H "HX-Request: true" \
        -d '{"intent": "Find tasks about code"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Any

from agenticapi import AgenticApp, HTMLResult, HtmxHeaders, Intent
from agenticapi.interface.htmx import htmx_response_headers
from agenticapi.routing import AgentRouter

if TYPE_CHECKING:
    from agenticapi.runtime.context import AgentContext

# ---------------------------------------------------------------------------
# In-memory data store (shared across requests for demo purposes)
# ---------------------------------------------------------------------------

TODOS: list[dict[str, Any]] = [
    {"id": 1, "text": "Learn AgenticAPI", "done": True},
    {"id": 2, "text": "Build an HTMX app", "done": False},
    {"id": 3, "text": "Write code review", "done": False},
    {"id": 4, "text": "Deploy to production", "done": False},
]
_next_id = 5

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

_HTMX_CDN = "https://unpkg.com/htmx.org@2.0.4"

_CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; color: #1a1a2e; }
h1 { color: #4f46e5; margin-bottom: 1rem; }
.card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; margin: 0.5rem 0; }
.done { text-decoration: line-through; opacity: 0.5; }
input[type=text] { padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 4px; width: 70%; }
button { padding: 0.5rem 1rem; background: #4f46e5; color: white; border: none; border-radius: 4px; cursor: pointer; }
button:hover { background: #4338ca; }
.count { color: #6b7280; font-size: 0.9rem; margin-bottom: 0.5rem; }
.search { margin-bottom: 1rem; }
.htmx-indicator { display: none; }
.htmx-request .htmx-indicator { display: inline; }
"""


def _render_todo_item(todo: dict[str, Any]) -> str:
    cls = "card done" if todo["done"] else "card"
    check = "checked" if todo["done"] else ""
    text = html.escape(todo["text"])
    tid = todo["id"]
    return f'<div class="{cls}" id="todo-{tid}"><label><input type="checkbox" {check} disabled> {text}</label></div>'


def _render_todo_list(todos: list[dict[str, Any]]) -> str:
    done = sum(1 for t in todos if t["done"])
    items = "\n".join(_render_todo_item(t) for t in todos)
    return f'<div class="count">{len(todos)} items, {done} done</div>\n<div id="todo-items">{items}</div>'


def _render_full_page(todos: list[dict[str, Any]]) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>AgenticAPI + HTMX Todo</title>
  <style>{_CSS}</style>
  <script src="{_HTMX_CDN}"></script>
</head>
<body>
  <h1>Todo List <span class="htmx-indicator">Loading...</span></h1>

  <div class="search">
    <input type="text" name="query" placeholder="Search todos..."
           hx-post="/agent/todo.search"
           hx-trigger="keyup changed delay:300ms"
           hx-target="#todo-list"
           hx-headers='{{"Content-Type": "application/json"}}'
           hx-vals='js:JSON.stringify({{intent: event.target.value || "show all"}})' />
  </div>

  <form hx-post="/agent/todo.add"
        hx-target="#todo-list"
        hx-swap="innerHTML"
        hx-headers='{{"Content-Type": "application/json"}}'
        hx-vals='js:JSON.stringify({{intent: document.getElementById("new-todo").value}})'
        hx-on::after-request="document.getElementById('new-todo').value=''">
    <input type="text" id="new-todo" name="text" placeholder="Add a new todo..." />
    <button type="submit">Add</button>
  </form>

  <div id="todo-list" style="margin-top: 1rem;">
    {_render_todo_list(todos)}
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Router and endpoints
# ---------------------------------------------------------------------------

app = AgenticApp(title="HTMX Todo App", version="0.1.0")
todo_router = AgentRouter(prefix="todo", tags=["todo"])


@todo_router.agent_endpoint(
    name="list",
    description="Show the todo list (full page or HTMX fragment)",
    autonomy_level="auto",
)
async def todo_list(intent: Intent, context: AgentContext, htmx: HtmxHeaders) -> HTMLResult:
    """Return full page for browser, fragment for HTMX."""
    if htmx.is_htmx:
        return HTMLResult(content=_render_todo_list(TODOS))
    return HTMLResult(content=_render_full_page(TODOS))


@todo_router.agent_endpoint(
    name="add",
    description="Add a new todo item",
    autonomy_level="auto",
)
async def todo_add(intent: Intent, context: AgentContext, htmx: HtmxHeaders) -> HTMLResult:
    """Add a todo and return updated list with HX-Trigger header."""
    global _next_id
    text = intent.raw.strip()
    if text and text.lower() not in ("add", "add item", "add todo"):
        TODOS.append({"id": _next_id, "text": text, "done": False})
        _next_id += 1

    headers = htmx_response_headers(trigger="todoAdded")
    return HTMLResult(content=_render_todo_list(TODOS), headers=headers)


@todo_router.agent_endpoint(
    name="search",
    description="Search todos by keyword",
    autonomy_level="auto",
)
async def todo_search(intent: Intent, context: AgentContext, htmx: HtmxHeaders) -> HTMLResult:
    """Filter todos and return matching items as fragment."""
    query = intent.raw.strip().lower()
    if not query or query in ("show all", "list", "show"):
        filtered = TODOS
    else:
        filtered = [t for t in TODOS if query in t["text"].lower()]
    return HTMLResult(content=_render_todo_list(filtered))


app.include_router(todo_router)
