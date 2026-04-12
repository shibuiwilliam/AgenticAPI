"""File handling example: upload, download, and streaming.

Demonstrates:
- File upload via multipart form data with ``UploadedFiles`` injection
- File download via ``FileResult`` (bytes, streaming)
- Starlette ``Response`` passthrough for advanced use cases
- Backward-compatible JSON endpoints alongside file endpoints

Run with:
    uvicorn examples.10_file_handling.app:app --reload

Test with curl:
    # Upload a file (multipart)
    curl -X POST http://127.0.0.1:8000/agent/files.upload \
        -F 'intent=Analyze this document' \
        -F 'document=@README.md'

    # Download a CSV file
    curl -X POST http://127.0.0.1:8000/agent/files.export_csv \
        -H "Content-Type: application/json" \
        -d '{"intent": "Export sales data"}' \
        -o export.csv

    # Stream a large response
    curl -X POST http://127.0.0.1:8000/agent/files.stream \
        -H "Content-Type: application/json" \
        -d '{"intent": "Stream log data"}'

    # Normal JSON endpoint (backward compat)
    curl -X POST http://127.0.0.1:8000/agent/files.info \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show file handling capabilities"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from starlette.responses import StreamingResponse

from agenticapi.app import AgenticApp
from agenticapi.interface.response import AgentResponse, FileResult
from agenticapi.routing import AgentRouter

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.interface.upload import UploadedFiles
    from agenticapi.runtime.context import AgentContext


# --- Router ---

router = AgentRouter(prefix="files", tags=["files"])


@router.agent_endpoint(
    name="upload",
    description="Upload files for analysis. Accepts multipart form data.",
    autonomy_level="auto",
)
async def file_upload(intent: Intent, context: AgentContext, files: UploadedFiles) -> AgentResponse:
    """Accept uploaded files and return metadata about them."""
    file_info: list[dict[str, Any]] = []
    for name, upload in files.items():
        file_info.append(
            {
                "field_name": name,
                "filename": upload.filename,
                "content_type": upload.content_type,
                "size_bytes": upload.size,
            }
        )

    return AgentResponse(
        result={
            "intent": intent.raw,
            "files_received": len(files),
            "files": file_info,
        },
        reasoning=f"Received {len(files)} file(s) for analysis",
    )


@router.agent_endpoint(
    name="export_csv",
    description="Export data as a downloadable CSV file.",
    autonomy_level="auto",
)
async def export_csv(intent: Intent, context: AgentContext) -> FileResult:
    """Generate and return a CSV file."""
    csv_content = "name,role,score\nalice,admin,95\nbob,operator,87\ncharlie,viewer,72\n"
    return FileResult(
        content=csv_content.encode(),
        media_type="text/csv",
        filename="export.csv",
    )


@router.agent_endpoint(
    name="stream",
    description="Stream data in chunks (useful for large responses).",
    autonomy_level="auto",
)
async def stream_data(intent: Intent, context: AgentContext) -> StreamingResponse:
    """Return a streaming response with chunked data."""

    async def generate() -> Any:
        for i in range(5):
            yield f"data: chunk {i + 1} of 5\n".encode()
            await asyncio.sleep(0)  # Yield control for proper cancellation

    return StreamingResponse(generate(), media_type="text/plain")


@router.agent_endpoint(
    name="info",
    description="Show file handling capabilities (standard JSON response).",
    autonomy_level="auto",
)
async def file_info(intent: Intent, context: AgentContext) -> dict[str, Any]:
    """Normal JSON endpoint alongside file endpoints."""
    return {
        "capabilities": [
            "File upload via multipart/form-data",
            "CSV export via FileResult",
            "Streaming responses for large data",
        ],
        "supported_upload_types": ["any file via multipart"],
        "supported_download_types": ["CSV", "streaming text"],
    }


# --- App ---

app = AgenticApp(title="File Handling Example", version="0.1.0")
app.include_router(router)
