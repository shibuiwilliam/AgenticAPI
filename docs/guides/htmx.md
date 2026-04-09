# HTMX Support

AgenticAPI integrates with [HTMX](https://htmx.org) for building interactive web applications with partial page updates. Endpoints can detect HTMX requests and return HTML fragments instead of full pages.

## How It Works

```
Browser (with htmx.js)
  → Sends request with HX-Request: true header
  → AgenticAPI detects HTMX via HtmxHeaders (auto-injected)
  → Handler returns HTMLResult (fragment or full page)
  → HTMX swaps the fragment into the page
```

## HtmxHeaders

Declare `HtmxHeaders` in your handler signature — it's auto-injected like `AgentTasks` and `UploadedFiles`:

```python
from agenticapi import AgenticApp, HtmxHeaders, HTMLResult

app = AgenticApp()

@app.agent_endpoint(name="items")
async def items(intent, context, htmx: HtmxHeaders):
    if htmx.is_htmx:
        # Return just the fragment for partial swap
        return HTMLResult(content="<li>Item 1</li><li>Item 2</li>")
    # Full page for direct browser navigation
    return HTMLResult(content="""
        <html>
        <head><script src="https://unpkg.com/htmx.org"></script></head>
        <body>
            <ul hx-get="/agent/items" hx-trigger="load">Loading...</ul>
        </body>
        </html>
    """)
```

### Available Headers

| Property | Type | HTMX Header | Description |
|---|---|---|---|
| `is_htmx` | `bool` | `HX-Request` | True if request came from HTMX |
| `boosted` | `bool` | `HX-Boosted` | True if from an `hx-boost` element |
| `target` | `str \| None` | `HX-Target` | ID of the target element |
| `trigger` | `str \| None` | `HX-Trigger` | ID of the trigger element |
| `trigger_name` | `str \| None` | `HX-Trigger-Name` | Name of the trigger element |
| `current_url` | `str \| None` | `HX-Current-URL` | Current browser URL |
| `prompt` | `str \| None` | `HX-Prompt` | User response to `hx-prompt` |

## Response Headers

Use `htmx_response_headers()` to control HTMX client-side behavior:

```python
from agenticapi.interface.htmx import htmx_response_headers

@app.agent_endpoint(name="add_item")
async def add_item(intent, context, htmx: HtmxHeaders):
    # Tell HTMX to trigger a client event and use beforeend swap
    headers = htmx_response_headers(
        trigger="itemAdded",
        reswap="beforeend",
    )
    return HTMLResult(content="<li>New item</li>", headers=headers)
```

### Available Response Headers

| Parameter | HTMX Header | Description |
|---|---|---|
| `trigger` | `HX-Trigger` | Trigger client-side events |
| `trigger_after_settle` | `HX-Trigger-After-Settle` | Trigger after settling step |
| `trigger_after_swap` | `HX-Trigger-After-Swap` | Trigger after swap step |
| `redirect` | `HX-Redirect` | Redirect the browser |
| `refresh` | `HX-Refresh` | Full page refresh |
| `retarget` | `HX-Retarget` | Override swap target selector |
| `reswap` | `HX-Reswap` | Override swap strategy |
| `push_url` | `HX-Push-Url` | Push URL to browser history |
| `replace_url` | `HX-Replace-Url` | Replace current URL |

## Full Example: Todo App

```python
from agenticapi import AgenticApp, HtmxHeaders, HTMLResult
from agenticapi.interface.htmx import htmx_response_headers

app = AgenticApp(title="HTMX Todo")
todos = ["Buy milk", "Write tests"]

@app.agent_endpoint(name="list")
async def todo_list(intent, context, htmx: HtmxHeaders):
    items_html = "".join(f"<li>{t}</li>" for t in todos)
    if htmx.is_htmx:
        return HTMLResult(content=items_html)
    return HTMLResult(content=f"""
        <html>
        <head><script src="https://unpkg.com/htmx.org"></script></head>
        <body>
            <ul id="todos">{items_html}</ul>
            <input name="intent" hx-post="/agent/add"
                   hx-target="#todos" hx-swap="beforeend">
        </body>
        </html>
    """)

@app.agent_endpoint(name="add")
async def todo_add(intent, context, htmx: HtmxHeaders):
    todos.append(intent.raw)
    headers = htmx_response_headers(trigger="todoAdded")
    return HTMLResult(content=f"<li>{intent.raw}</li>", headers=headers)
```

## When to Use HTMX vs JSON

| Use case | Response type |
|---|---|
| API for programmatic clients | `dict` or `AgentResponse` (JSON) |
| Full HTML page | `HTMLResult` |
| HTMX partial update | `HTMLResult` (fragment) with `htmx.is_htmx` check |
| Plain text (status, logs) | `PlainTextResult` |
| File download | `FileResult` |

All response types work in the same app — each endpoint chooses independently.

## Example

See [`examples/12_htmx/`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/12_htmx) for a complete HTMX todo app with list, add, search, and toggle endpoints.
