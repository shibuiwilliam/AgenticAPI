"""Tests for QueueTool."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import ToolError
from agenticapi.runtime.tools.queue import QueueTool


class TestQueueToolDefinition:
    def test_definition_has_correct_name(self) -> None:
        tool = QueueTool(name="my_queue")
        assert tool.definition.name == "my_queue"

    def test_definition_has_read_write_capabilities(self) -> None:
        tool = QueueTool()
        caps = [c.value for c in tool.definition.capabilities]
        assert "read" in caps
        assert "write" in caps


class TestQueueToolOperations:
    async def test_enqueue_and_dequeue(self) -> None:
        tool = QueueTool()
        await tool.invoke(action="enqueue", queue_name="tasks", message={"id": 1})
        result = await tool.invoke(action="dequeue", queue_name="tasks")
        assert result == {"id": 1}

    async def test_dequeue_empty_returns_none(self) -> None:
        tool = QueueTool()
        result = await tool.invoke(action="dequeue", queue_name="empty")
        assert result is None

    async def test_peek_returns_without_removing(self) -> None:
        tool = QueueTool()
        await tool.invoke(action="enqueue", queue_name="q", message="msg1")
        peeked = await tool.invoke(action="peek", queue_name="q")
        assert peeked == "msg1"
        # Should still be there
        dequeued = await tool.invoke(action="dequeue", queue_name="q")
        assert dequeued == "msg1"

    async def test_peek_empty_returns_none(self) -> None:
        tool = QueueTool()
        result = await tool.invoke(action="peek", queue_name="empty")
        assert result is None

    async def test_size_returns_queue_length(self) -> None:
        tool = QueueTool()
        await tool.invoke(action="enqueue", queue_name="q", message="a")
        await tool.invoke(action="enqueue", queue_name="q", message="b")
        size = await tool.invoke(action="size", queue_name="q")
        assert size == 2

    async def test_size_empty_queue_returns_zero(self) -> None:
        tool = QueueTool()
        size = await tool.invoke(action="size", queue_name="new")
        assert size == 0

    async def test_fifo_order(self) -> None:
        tool = QueueTool()
        await tool.invoke(action="enqueue", queue_name="q", message="first")
        await tool.invoke(action="enqueue", queue_name="q", message="second")
        first = await tool.invoke(action="dequeue", queue_name="q")
        second = await tool.invoke(action="dequeue", queue_name="q")
        assert first == "first"
        assert second == "second"

    async def test_invalid_action_raises(self) -> None:
        tool = QueueTool()
        with pytest.raises(ToolError, match="Invalid queue action"):
            await tool.invoke(action="invalid", queue_name="q")

    async def test_enqueue_full_raises(self) -> None:
        tool = QueueTool(max_size=1)
        await tool.invoke(action="enqueue", queue_name="q", message="a")
        with pytest.raises(ToolError, match="full"):
            await tool.invoke(action="enqueue", queue_name="q", message="b")

    async def test_separate_named_queues(self) -> None:
        tool = QueueTool()
        await tool.invoke(action="enqueue", queue_name="q1", message="msg1")
        await tool.invoke(action="enqueue", queue_name="q2", message="msg2")
        r1 = await tool.invoke(action="dequeue", queue_name="q1")
        r2 = await tool.invoke(action="dequeue", queue_name="q2")
        assert r1 == "msg1"
        assert r2 == "msg2"


class TestQueueToolTimeout:
    async def test_dequeue_with_timeout_returns_none_on_empty(self) -> None:
        tool = QueueTool()
        result = await tool.invoke(action="dequeue", queue_name="empty", timeout=0.05)
        assert result is None

    async def test_dequeue_without_timeout_returns_none_immediately(self) -> None:
        tool = QueueTool()
        result = await tool.invoke(action="dequeue", queue_name="empty")
        assert result is None
