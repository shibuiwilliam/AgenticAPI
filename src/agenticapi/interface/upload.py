"""File upload support for agent endpoints.

Provides ``UploadFile`` for representing uploaded files and the
``UploadedFiles`` type alias for handler parameter injection.

Handlers that declare an ``UploadedFiles`` parameter receive a dict
of uploaded files automatically when the request uses
``multipart/form-data`` encoding.

Usage:
    @app.agent_endpoint(name="documents")
    async def handle_doc(
        intent: Intent,
        context: AgentContext,
        files: UploadedFiles,
    ) -> dict[str, Any]:
        pdf = files["document"]
        return {"filename": pdf.filename, "size": pdf.size}

    # curl -X POST http://localhost:8000/agent/documents \\
    #     -F 'intent=Analyze this document' \\
    #     -F 'document=@report.pdf'
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class UploadFile:
    """An uploaded file from a multipart form request.

    Attributes:
        filename: Original filename from the upload.
        content_type: MIME type of the uploaded file.
        content: Raw bytes of the file content.
        size: File size in bytes.
    """

    filename: str
    content_type: str
    content: bytes
    size: int


type UploadedFiles = dict[str, UploadFile]
"""Dict mapping field names to uploaded files.

Use as a handler parameter type annotation for automatic injection::

    async def handler(intent, context, files: UploadedFiles):
        doc = files["my_file"]
"""
