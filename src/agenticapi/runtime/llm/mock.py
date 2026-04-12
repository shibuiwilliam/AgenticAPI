"""Mock LLM backend for testing.

Provides a deterministic LLM backend that returns pre-configured responses
in order, useful for unit and integration tests.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMChunk, LLMPrompt, LLMResponse, LLMUsage, ToolCall

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class MockBackend:
    """A mock LLM backend that returns pre-configured responses.

    Responses are returned in FIFO order. Raises CodeGenerationError
    when all responses have been consumed.

    Example:
        backend = MockBackend(responses=["SELECT COUNT(*) FROM orders"])
        response = await backend.generate(prompt)
        assert response.content == "SELECT COUNT(*) FROM orders"
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        structured_responses: list[dict[str, Any]] | None = None,
        tool_call_responses: list[list[ToolCall]] | None = None,
    ) -> None:
        """Initialize the mock backend.

        Args:
            responses: List of response strings to return in order.
                Used when neither ``LLMPrompt.response_schema`` nor
                ``LLMPrompt.tools`` is set.
            structured_responses: List of pre-built dicts the backend
                returns when the prompt carries a ``response_schema``.
                Each dict is JSON-serialised into ``LLMResponse.content``
                so the consumer can parse it back into a Pydantic model.
                Falls back to a synthesised stub matching the schema's
                ``required`` fields when this list is empty.
            tool_call_responses: Phase E3 — list of pre-built tool-call
                bundles the backend returns when ``LLMPrompt.tools`` is
                set. Each entry is a list of one-or-more
                :class:`ToolCall`s representing what the model would
                emit on a single turn (most calls are length-1; a
                length-2 list represents the model batching two tool
                invocations into one response). Falls back to an empty
                tool-call list (and a synthesised text response) when
                this list is empty so existing tests stay green.
        """
        self._responses: list[str] = list(responses) if responses else []
        self._structured_responses: list[dict[str, Any]] = list(structured_responses) if structured_responses else []
        self._tool_call_responses: list[list[ToolCall]] = list(tool_call_responses) if tool_call_responses else []
        self._call_count: int = 0
        self._prompts: list[LLMPrompt] = []

    @property
    def model_name(self) -> str:
        """The name of the mock model."""
        return "mock"

    @property
    def call_count(self) -> int:
        """Number of generate calls made."""
        return self._call_count

    @property
    def prompts(self) -> list[LLMPrompt]:
        """All prompts that were sent to this backend."""
        return list(self._prompts)

    def add_response(self, response: str) -> None:
        """Add a response to the queue.

        Args:
            response: The response string to add.
        """
        self._responses.append(response)

    def add_structured_response(self, response: dict[str, Any]) -> None:
        """Add a structured (schema-conforming) response to the queue.

        Args:
            response: The dict the backend will return on the next call
                that includes a ``response_schema`` in the prompt.
        """
        self._structured_responses.append(response)

    def add_tool_call_response(self, calls: ToolCall | list[ToolCall]) -> None:
        """Queue a native function-call response for the next tools-enabled call.

        Args:
            calls: Either one :class:`ToolCall` (the common case) or a
                list representing the model batching multiple calls
                into a single response.
        """
        bundle = [calls] if isinstance(calls, ToolCall) else list(calls)
        self._tool_call_responses.append(bundle)

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        """Return the next pre-configured response.

        Branch order, in priority:

        1. ``prompt.tools`` set **and** a tool-call response queued →
           return an :class:`LLMResponse` with the queued
           :class:`ToolCall`s and an empty content string. This is
           the Phase E3 native-function-calling path.
        2. ``prompt.response_schema`` set → return a structured
           (JSON) response from the queue or synthesised from the
           schema. This is the D4 typed-intent path.
        3. Otherwise → return the next free-form text response.

        Args:
            prompt: The LLM prompt (recorded for later inspection).

        Returns:
            An LLMResponse with the next pre-configured content.

        Raises:
            CodeGenerationError: If no response is available for the
                requested mode.
        """
        self._prompts.append(prompt)
        self._call_count += 1

        # Phase E3: tools-enabled path. The model "wants to call a
        # function" — return the queued ToolCall bundle. Empty
        # content + finish_reason="tool_calls" mirrors what the real
        # backends emit on this path.
        if prompt.tools and self._tool_call_responses:
            calls = self._tool_call_responses.pop(0)
            return LLMResponse(
                content="",
                usage=LLMUsage(
                    input_tokens=len(prompt.system) // 4,
                    output_tokens=sum(len(json.dumps(c.arguments)) for c in calls) // 4,
                ),
                model="mock",
                tool_calls=calls,
                finish_reason="tool_calls",
            )

        # tool_choice="required" forces a tool call even when none is
        # queued — synthesise a call to the first declared tool.
        if prompt.tools and prompt.tool_choice == "required":
            first_tool = prompt.tools[0]
            synth = ToolCall(
                id="mock_required_0",
                name=first_tool.get("name", "unknown"),
                arguments={},
            )
            return LLMResponse(
                content="",
                usage=LLMUsage(input_tokens=len(prompt.system) // 4, output_tokens=10),
                model="mock",
                tool_calls=[synth],
                finish_reason="tool_calls",
            )

        if prompt.response_schema is not None:
            payload: dict[str, Any]
            if self._structured_responses:
                payload = self._structured_responses.pop(0)
            else:
                payload = _synthesise_from_schema(prompt.response_schema)
            content = json.dumps(payload)
            return LLMResponse(
                content=content,
                usage=LLMUsage(
                    input_tokens=len(prompt.system) // 4,
                    output_tokens=len(content) // 4,
                ),
                model="mock",
                finish_reason="stop",
            )

        if not self._responses:
            raise CodeGenerationError("MockBackend: no more responses available")

        content = self._responses.pop(0)
        return LLMResponse(
            content=content,
            usage=LLMUsage(input_tokens=len(prompt.system) // 4, output_tokens=len(content) // 4),
            model="mock",
        )

    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]:
        """Stream the next pre-configured response in chunks.

        Splits the response content into word-level chunks for realistic
        streaming simulation.

        Args:
            prompt: The LLM prompt (recorded for later inspection).

        Yields:
            LLMChunk objects, with the final chunk having is_final=True.

        Raises:
            CodeGenerationError: If all responses have been consumed.
        """
        response = await self.generate(prompt)
        words = response.content.split(" ")
        for i, word in enumerate(words):
            is_last = i == len(words) - 1
            chunk_content = word if is_last else word + " "
            yield LLMChunk(content=chunk_content, is_final=is_last)


def _synthesise_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Build a stub object that satisfies a JSON Schema.

    Used by ``MockBackend`` when no explicit ``structured_responses``
    are queued. Walks the schema's ``properties`` and produces a value
    for every required field using sensible defaults per JSON-Schema
    type. Unknown types fall back to ``None``.
    """
    if "$defs" in schema and "$ref" in schema:
        # Resolve the top-level $ref into one of the $defs entries.
        ref = schema["$ref"]
        ref_name = ref.rsplit("/", 1)[-1]
        target = schema["$defs"].get(ref_name, {})
        merged: dict[str, Any] = {**schema, **target}
        merged.pop("$ref", None)
        return _synthesise_from_schema(merged)

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    out: dict[str, Any] = {}

    for name, prop_schema in properties.items():
        if name not in required and "default" in prop_schema:
            out[name] = prop_schema["default"]
            continue
        if name not in required:
            continue
        out[name] = _value_for_property(prop_schema, schema.get("$defs", {}))
    return out


def _value_for_property(prop: dict[str, Any], defs: dict[str, Any]) -> Any:
    """Synthesise a single value for a JSON-Schema property entry."""
    if "default" in prop:
        return prop["default"]
    if "$ref" in prop:
        ref_name = prop["$ref"].rsplit("/", 1)[-1]
        target = defs.get(ref_name, {})
        return _synthesise_from_schema({**target, "$defs": defs})
    if prop.get("enum"):
        return prop["enum"][0]
    if prop.get("anyOf"):
        return _value_for_property(prop["anyOf"][0], defs)
    type_ = prop.get("type")
    if type_ == "string":
        return ""
    if type_ == "integer":
        return 0
    if type_ == "number":
        return 0.0
    if type_ == "boolean":
        return False
    if type_ == "array":
        return []
    if type_ == "object":
        return _synthesise_from_schema({**prop, "$defs": defs})
    return None
