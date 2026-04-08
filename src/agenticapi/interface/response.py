"""Agent response model, file results, and formatting.

Provides the AgentResponse data class representing the result of an
agent operation, FileResult for file download responses, and
ResponseFormatter for serializing responses into different output formats.
"""

from __future__ import annotations

import collections.abc
from dataclasses import asdict, dataclass, field
from typing import Any

from starlette.responses import FileResponse, Response, StreamingResponse


@dataclass(slots=True)
class AgentResponse:
    """Response from an agent endpoint.

    Captures the result, status, and metadata of an agent operation.

    Attributes:
        result: The primary output from the agent operation.
        status: Response status. One of "completed", "pending_approval",
            "error", or "clarification_needed".
        generated_code: The code that was generated and executed (if any).
        reasoning: LLM reasoning for the generated code (if any).
        confidence: Confidence in the result (0.0-1.0).
        execution_trace_id: Identifier for the audit trace of this operation.
        follow_up_suggestions: Suggested follow-up actions for the user.
        error: Error message if status is "error".
        approval_request: Approval request details if status is "pending_approval".
    """

    result: Any
    status: str = "completed"
    generated_code: str | None = None
    reasoning: str | None = None
    confidence: float = 1.0
    execution_trace_id: str | None = None
    follow_up_suggestions: list[str] = field(default_factory=list)
    error: str | None = None
    approval_request: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the response to a JSON-compatible dictionary.

        Excludes None values for cleaner output.

        Returns:
            A dictionary representation of the response.
        """
        raw = asdict(self)
        # Remove None values for cleaner JSON output
        return {k: v for k, v in raw.items() if v is not None}


class ResponseFormatter:
    """Formats AgentResponse for different output formats.

    Provides methods for JSON and plain-text serialization.

    Example:
        formatter = ResponseFormatter()
        json_dict = formatter.format_json(response)
        text = formatter.format_text(response)
    """

    def format_json(self, response: AgentResponse) -> dict[str, Any]:
        """Format the response as a JSON-compatible dictionary.

        Includes all fields, filtering out None values.

        Args:
            response: The agent response to format.

        Returns:
            A JSON-compatible dictionary.
        """
        return response.to_dict()

    def format_text(self, response: AgentResponse) -> str:
        """Format the response as human-readable plain text.

        Args:
            response: The agent response to format.

        Returns:
            A human-readable text representation.
        """
        parts: list[str] = []

        parts.append(f"Status: {response.status}")

        if response.error:
            parts.append(f"Error: {response.error}")
        elif response.result is not None:
            parts.append(f"Result: {response.result}")

        if response.reasoning:
            parts.append(f"Reasoning: {response.reasoning}")

        if response.confidence < 1.0:
            parts.append(f"Confidence: {response.confidence:.2f}")

        if response.follow_up_suggestions:
            parts.append("Suggestions:")
            for suggestion in response.follow_up_suggestions:
                parts.append(f"  - {suggestion}")

        if response.execution_trace_id:
            parts.append(f"Trace ID: {response.execution_trace_id}")

        return "\n".join(parts)


@dataclass(slots=True)
class FileResult:
    """Convenience wrapper for returning files from agent endpoints.

    Handlers return this instead of constructing Starlette responses
    directly. The framework converts it to the appropriate response type
    based on the ``content`` field:

    - ``bytes`` → inline ``Response`` with the given media type
    - ``str`` → ``FileResponse`` (interpreted as a file path)
    - async/sync iterable → ``StreamingResponse``

    Example:
        @app.agent_endpoint(name="export")
        async def export_csv(intent, context):
            csv_data = "name,value\\nalice,42\\nbob,17"
            return FileResult(
                content=csv_data.encode(),
                media_type="text/csv",
                filename="export.csv",
            )

    Attributes:
        content: File data — bytes, a file path string, or an iterable for streaming.
        media_type: MIME type of the response (e.g., "application/pdf", "image/png").
        filename: Suggested download filename. Sets the Content-Disposition header.
        headers: Additional response headers.
    """

    content: bytes | str | Any
    media_type: str = "application/octet-stream"
    filename: str | None = None
    headers: dict[str, str] | None = None

    def to_response(self) -> Response:
        """Convert to the appropriate Starlette response type.

        Returns:
            A Starlette Response, FileResponse, or StreamingResponse.
        """
        extra_headers: dict[str, str] = dict(self.headers) if self.headers else {}
        if self.filename:
            # Sanitize filename: remove path separators and escape quotes
            safe_name = self.filename.replace("/", "_").replace("\\", "_").replace('"', '\\"')
            extra_headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'

        if isinstance(self.content, bytes):
            return Response(
                content=self.content,
                media_type=self.media_type,
                headers=extra_headers or None,
            )

        if isinstance(self.content, str):
            # Resolve the path and ensure it's absolute (prevent path traversal)
            import pathlib

            resolved = pathlib.Path(self.content).resolve()
            return FileResponse(
                path=str(resolved),
                media_type=self.media_type,
                filename=self.filename,
                headers=extra_headers or None,
            )

        if isinstance(self.content, (collections.abc.AsyncIterator, collections.abc.Iterator)):
            return StreamingResponse(
                content=self.content,
                media_type=self.media_type,
                headers=extra_headers or None,
            )

        # Fallback: treat as bytes-like
        return Response(
            content=bytes(self.content),
            media_type=self.media_type,
            headers=extra_headers or None,
        )
