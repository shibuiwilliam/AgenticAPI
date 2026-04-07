"""Agent response model and formatting.

Provides the AgentResponse data class representing the result of an
agent operation, and ResponseFormatter for serializing responses
into different output formats.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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
