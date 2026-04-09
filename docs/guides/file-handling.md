# File Upload & Download

AgenticAPI supports file uploads via multipart form data and file downloads via `FileResult`, Starlette `Response` passthrough, and streaming responses.

## File Upload

### How It Works

When a request has `Content-Type: multipart/form-data`, the handler parses form fields and file fields separately:

- The `intent` form field becomes the natural language request
- File fields become `UploadFile` objects accessible to the handler

```
POST /agent/documents (multipart/form-data)
  → Parse "intent" from form field
  → Parse file fields into UploadFile objects
  → Store in context.metadata["files"]
  → Auto-inject into handler if UploadedFiles parameter present
```

### Basic Upload

```python
from agenticapi import AgenticApp
from agenticapi.interface.upload import UploadedFiles

app = AgenticApp()

@app.agent_endpoint(name="analyze")
async def analyze(intent, context, files: UploadedFiles):
    doc = files["document"]
    return {
        "filename": doc.filename,
        "content_type": doc.content_type,
        "size": doc.size,
    }
```

```bash
curl -X POST http://localhost:8000/agent/analyze \
    -F 'intent=Analyze this document' \
    -F 'document=@report.pdf'
```

### UploadFile Properties

Each uploaded file is an `UploadFile` instance with:

| Property | Type | Description |
|---|---|---|
| `filename` | `str` | Original filename from the upload |
| `content_type` | `str` | MIME type (e.g., `application/pdf`) |
| `content` | `bytes` | Raw file data |
| `size` | `int` | File size in bytes |

### Limits & Safety

- **Maximum file size**: 50 MB per file. Requests exceeding this return HTTP 413.
- **In-memory**: Files are read fully into memory. The size limit prevents OOM.
- **All MIME types accepted**: No Content-Type filtering by default. Validate in your handler if needed.

### Multiple Files

```python
@app.agent_endpoint(name="batch")
async def batch_upload(intent, context, files: UploadedFiles):
    return {
        "file_count": len(files),
        "files": [
            {"name": f.filename, "size": f.size}
            for f in files.values()
        ],
    }
```

```bash
curl -X POST http://localhost:8000/agent/batch \
    -F 'intent=Process these files' \
    -F 'file1=@image.png' \
    -F 'file2=@data.csv'
```

### Accessing Files via Context

Files are also available via `context.metadata["files"]` even without the `UploadedFiles` parameter:

```python
@app.agent_endpoint(name="docs")
async def handler(intent, context):
    files = context.metadata.get("files", {})
    if files:
        doc = files["document"]
        return {"received": doc.filename}
    return {"received": None}
```

### JSON Requests Still Work

Endpoints that support file uploads also accept standard JSON requests. The content type is detected automatically:

```bash
# JSON (application/json) — works as before
curl -X POST http://localhost:8000/agent/analyze \
    -H "Content-Type: application/json" \
    -d '{"intent": "Analyze something"}'

# Multipart (multipart/form-data) — also works
curl -F 'intent=Analyze this' -F 'doc=@file.pdf' \
    http://localhost:8000/agent/analyze
```

---

## File Download

### FileResult

The `FileResult` helper lets handlers return files without constructing Starlette responses directly:

```python
from agenticapi.interface.response import FileResult

@app.agent_endpoint(name="export")
async def export_csv(intent, context):
    csv_data = "name,score\nalice,95\nbob,87\n"
    return FileResult(
        content=csv_data.encode(),
        media_type="text/csv",
        filename="export.csv",
    )
```

```bash
curl -X POST http://localhost:8000/agent/export \
    -H "Content-Type: application/json" \
    -d '{"intent": "Export data"}' -o export.csv
```

### FileResult Content Types

`FileResult` auto-selects the right Starlette response based on the `content` field:

| `content` type | Starlette response | Use case |
|---|---|---|
| `bytes` | `Response` | In-memory data (CSV, JSON, small files) |
| `str` (file path) | `FileResponse` | Serve file from disk |
| Iterator/AsyncIterator | `StreamingResponse` | Large or generated data |

#### Bytes Content

```python
return FileResult(
    content=b"Hello, World!",
    media_type="text/plain",
    filename="hello.txt",
)
```

#### File Path

```python
return FileResult(
    content="/path/to/report.pdf",
    media_type="application/pdf",
    filename="report.pdf",
)
```

#### Streaming

```python
import asyncio

async def generate_large_csv():
    yield b"id,name,value\n"
    for i in range(100_000):
        yield f"{i},item_{i},{i * 1.5}\n".encode()
        if i % 1000 == 0:
            await asyncio.sleep(0)  # Yield control for cancellation

return FileResult(
    content=generate_large_csv(),
    media_type="text/csv",
    filename="large_export.csv",
)
```

### FileResult Properties

| Property | Type | Default | Description |
|---|---|---|---|
| `content` | `bytes \| str \| Any` | (required) | File data, path, or iterable |
| `media_type` | `str` | `application/octet-stream` | MIME type |
| `filename` | `str \| None` | `None` | Sets `Content-Disposition` for download |
| `headers` | `dict[str, str] \| None` | `None` | Additional response headers |

### Direct Starlette Response

For advanced use cases, handlers can return Starlette `Response`, `FileResponse`, or `StreamingResponse` directly:

```python
from starlette.responses import StreamingResponse

@app.agent_endpoint(name="stream")
async def stream_handler(intent, context):
    async def generate():
        for i in range(10):
            yield f"data: event {i}\n\n".encode()

    return StreamingResponse(generate(), media_type="text/event-stream")
```

Any Starlette `Response` subclass is passed through to the client without JSON wrapping.

### Backward Compatibility

Handlers that return dicts or `AgentResponse` objects continue to produce JSON responses as before. The file response passthrough only activates when the handler returns a `Response`, `FileResponse`, `StreamingResponse`, `FileResult`, `HTMLResult`, or `PlainTextResult`.

---

## HTML and Plain Text Responses

In addition to `FileResult`, two convenience types are provided for common non-JSON response types:

### HTMLResult

Return HTML pages directly from agent endpoints:

```python
from agenticapi.interface.response import HTMLResult

@app.agent_endpoint(name="dashboard")
async def dashboard(intent, context):
    return HTMLResult(content="<h1>Dashboard</h1><p>Welcome!</p>")
```

The response has `Content-Type: text/html`. Supports optional `status_code` and `headers`.

### PlainTextResult

Return plain text responses:

```python
from agenticapi.interface.response import PlainTextResult

@app.agent_endpoint(name="status")
async def status(intent, context):
    return PlainTextResult(content="Status: OK\nUptime: 42h")
```

The response has `Content-Type: text/plain`. Supports optional `status_code` and `headers`.

### Mixing Response Types

A single app can serve JSON, HTML, plain text, and file downloads — each endpoint chooses its own response type:

```python
@app.agent_endpoint(name="api")
async def api(intent, context):
    return {"data": "json"}          # -> JSON

@app.agent_endpoint(name="page")
async def page(intent, context):
    return HTMLResult(content="<h1>HTML</h1>")  # -> text/html

@app.agent_endpoint(name="health")
async def health(intent, context):
    return PlainTextResult(content="OK")  # -> text/plain

@app.agent_endpoint(name="export")
async def export(intent, context):
    return FileResult(content=b"data", media_type="text/csv", filename="export.csv")  # -> file download
```

---

## Examples

- [`examples/10_file_handling/`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/10_file_handling) — Upload, CSV download, and streaming
- [`examples/11_html_responses/`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/11_html_responses) — HTML pages, plain text, and mixed response types
