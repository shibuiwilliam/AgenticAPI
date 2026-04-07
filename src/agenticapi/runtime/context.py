"""Context management for agent operations.

Provides data structures for managing the context window passed
to LLM prompts and tracking agent execution metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextItem:
    """A single item of context to include in the LLM prompt.

    Attributes:
        key: Unique identifier for this context item.
        value: The text content of this context.
        source: Where this context originated from (e.g., "session", "tool", "user").
        priority: Higher priority items are included first (default 0).
    """

    key: str
    value: str
    source: str
    priority: int = 0


@dataclass(slots=True)
class ContextWindow:
    """Manages a window of context items within a token budget.

    Items are sorted by priority (descending) when building the
    final context string. Provides token estimation for budget management.

    Attributes:
        max_tokens: Maximum estimated tokens for the context window.
        items: The context items in this window.
    """

    max_tokens: int = 100_000
    items: list[ContextItem] = field(default_factory=list)

    def add(self, item: ContextItem) -> None:
        """Add a context item to the window.

        Items that would exceed the token budget are silently dropped.

        Args:
            item: The context item to add.
        """
        new_tokens = self.estimated_tokens() + self._estimate_item_tokens(item)
        if new_tokens <= self.max_tokens:
            self.items.append(item)

    def build(self) -> str:
        """Build the final context string from all items.

        Items are sorted by priority (highest first) and concatenated
        with section headers.

        Returns:
            The assembled context string.
        """
        if not self.items:
            return ""

        sorted_items = sorted(self.items, key=lambda x: x.priority, reverse=True)
        sections: list[str] = []
        for item in sorted_items:
            sections.append(f"[{item.key} (source: {item.source})]\n{item.value}")
        return "\n\n".join(sections)

    def estimated_tokens(self) -> int:
        """Estimate the total token count of all items.

        Uses a rough heuristic of 1 token per 4 characters.

        Returns:
            Estimated token count.
        """
        total_chars = sum(len(item.key) + len(item.value) + len(item.source) + 20 for item in self.items)
        return total_chars // 4

    @staticmethod
    def _estimate_item_tokens(item: ContextItem) -> int:
        """Estimate tokens for a single context item.

        Args:
            item: The context item to estimate.

        Returns:
            Estimated token count.
        """
        return (len(item.key) + len(item.value) + len(item.source) + 20) // 4

    def clear(self) -> None:
        """Remove all items from the context window."""
        self.items.clear()


@dataclass(slots=True)
class AgentContext:
    """Execution context for an agent operation.

    Carries metadata about the current request and provides
    the context window for LLM prompt assembly.

    Attributes:
        trace_id: Unique identifier for tracing this operation.
        endpoint_name: The agent endpoint handling this request.
        session_id: Optional session identifier for multi-turn conversations.
        user_id: Optional user identifier.
        metadata: Arbitrary key-value metadata.
        context_window: The context window for LLM prompts.
    """

    trace_id: str
    endpoint_name: str
    session_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    context_window: ContextWindow = field(default_factory=ContextWindow)
