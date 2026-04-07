"""Queue tool for agent message passing.

Provides an in-memory async queue for agent operations.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.base import ToolCapability, ToolDefinition

logger = structlog.get_logger(__name__)


class QueueTool:
    """An in-memory async queue tool for message passing.

    Provides enqueue, dequeue, peek, and size operations
    on named queues.

    Example:
        tool = QueueTool()
        await tool.invoke(action="enqueue", queue_name="tasks", message={"id": 1})
        msg = await tool.invoke(action="dequeue", queue_name="tasks")
    """

    _ALLOWED_ACTIONS: frozenset[str] = frozenset({"enqueue", "dequeue", "peek", "size"})

    def __init__(
        self,
        *,
        name: str = "queue",
        description: str = "In-memory async message queue",
        max_size: int = 0,
    ) -> None:
        """Initialize the queue tool.

        Args:
            name: The name for this tool instance.
            description: Human-readable description.
            max_size: Maximum queue size (0 for unlimited).
        """
        self._name = name
        self._description = description
        self._max_size = max_size
        self._queues: dict[str, asyncio.Queue[Any]] = {}

    @property
    def definition(self) -> ToolDefinition:
        """Return the tool's metadata definition."""
        return ToolDefinition(
            name=self._name,
            description=self._description,
            capabilities=[ToolCapability.READ, ToolCapability.WRITE],
            parameters_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["enqueue", "dequeue", "peek", "size"],
                        "description": "Queue operation to perform",
                    },
                    "queue_name": {"type": "string", "description": "Name of the queue"},
                    "message": {"description": "Message to enqueue", "default": None},
                    "timeout": {
                        "type": "number",
                        "description": "Timeout for dequeue in seconds",
                        "default": None,
                    },
                },
                "required": ["action", "queue_name"],
            },
        )

    def _get_queue(self, queue_name: str) -> asyncio.Queue[Any]:
        """Get or create a named queue."""
        if queue_name not in self._queues:
            self._queues[queue_name] = asyncio.Queue(maxsize=self._max_size)
        return self._queues[queue_name]

    async def invoke(
        self,
        *,
        action: str,
        queue_name: str,
        message: Any = None,
        timeout: float | None = None,
    ) -> Any:
        """Perform a queue operation.

        Args:
            action: One of "enqueue", "dequeue", "peek", "size".
            queue_name: Name of the queue to operate on.
            message: Message to enqueue (required for "enqueue").
            timeout: Timeout for dequeue in seconds.

        Returns:
            The message for "dequeue"/"peek", int for "size", None for "enqueue".

        Raises:
            ToolError: If the action is invalid or the operation fails.
        """
        if action not in self._ALLOWED_ACTIONS:
            raise ToolError(f"Invalid queue action '{action}'. Allowed: {sorted(self._ALLOWED_ACTIONS)}")

        logger.info("queue_tool_invoke", tool_name=self._name, action=action, queue_name=queue_name)

        queue = self._get_queue(queue_name)

        if action == "enqueue":
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull as exc:
                raise ToolError(f"Queue '{queue_name}' is full (max_size={self._max_size})") from exc
            return None
        elif action == "dequeue":
            try:
                if timeout is not None:
                    return await asyncio.wait_for(queue.get(), timeout=timeout)
                return queue.get_nowait()
            except asyncio.QueueEmpty:
                return None
            except TimeoutError:
                return None
        elif action == "peek":
            if queue.empty():
                return None
            # Note: peek is not atomic. In concurrent scenarios, the peeked
            # item may be consumed by another coroutine between get and put.
            # For Phase 1, this is acceptable. Phase 2 should use a deque.
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return None
            await queue.put(item)
            return item
        elif action == "size":
            return queue.qsize()
        return None
