"""Mock LLM backend for testing.

Provides a deterministic LLM backend that returns pre-configured responses
in order, useful for unit and integration tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agenticapi.exceptions import CodeGenerationError
from agenticapi.runtime.llm.base import LLMChunk, LLMPrompt, LLMResponse, LLMUsage

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

    def __init__(self, responses: list[str] | None = None) -> None:
        """Initialize the mock backend.

        Args:
            responses: List of response strings to return in order.
        """
        self._responses: list[str] = list(responses) if responses else []
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

    async def generate(self, prompt: LLMPrompt) -> LLMResponse:
        """Return the next pre-configured response.

        Args:
            prompt: The LLM prompt (recorded for later inspection).

        Returns:
            An LLMResponse with the next pre-configured content.

        Raises:
            CodeGenerationError: If all responses have been consumed.
        """
        self._prompts.append(prompt)
        self._call_count += 1

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
        # Decrement call_count since generate already incremented it,
        # but we don't want to double-count. Actually generate was already
        # called, so the count is correct. We just need to yield chunks.
        words = response.content.split(" ")
        for i, word in enumerate(words):
            is_last = i == len(words) - 1
            chunk_content = word if is_last else word + " "
            yield LLMChunk(content=chunk_content, is_final=is_last)
