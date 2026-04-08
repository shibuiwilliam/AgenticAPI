"""Tests for AgentTasks background task support."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from httpx import ASGITransport, AsyncClient

from agenticapi.app import AgenticApp
from agenticapi.interface.tasks import AgentTasks

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


class TestAgentTasks:
    async def test_add_and_execute_sync_task(self) -> None:
        results: list[str] = []

        def sync_task(msg: str) -> None:
            results.append(msg)

        tasks = AgentTasks()
        tasks.add_task(sync_task, "hello")
        tasks.add_task(sync_task, "world")

        assert tasks.pending_count == 2
        await tasks.execute()
        assert results == ["hello", "world"]

    async def test_add_and_execute_async_task(self) -> None:
        results: list[int] = []

        async def async_task(value: int) -> None:
            results.append(value)

        tasks = AgentTasks()
        tasks.add_task(async_task, 42)
        await tasks.execute()
        assert results == [42]

    async def test_mixed_sync_and_async_tasks(self) -> None:
        order: list[str] = []

        def sync_step() -> None:
            order.append("sync")

        async def async_step() -> None:
            order.append("async")

        tasks = AgentTasks()
        tasks.add_task(sync_step)
        tasks.add_task(async_step)
        tasks.add_task(sync_step)
        await tasks.execute()
        assert order == ["sync", "async", "sync"]

    async def test_task_failure_does_not_block_others(self) -> None:
        results: list[str] = []

        def good_task(msg: str) -> None:
            results.append(msg)

        def bad_task() -> None:
            raise RuntimeError("boom")

        tasks = AgentTasks()
        tasks.add_task(good_task, "before")
        tasks.add_task(bad_task)
        tasks.add_task(good_task, "after")
        await tasks.execute()
        # Both good tasks should run despite the middle one failing
        assert results == ["before", "after"]

    async def test_kwargs_supported(self) -> None:
        results: dict[str, Any] = {}

        def capture(**kwargs: Any) -> None:
            results.update(kwargs)

        tasks = AgentTasks()
        tasks.add_task(capture, user_id=1, action="signup")
        await tasks.execute()
        assert results == {"user_id": 1, "action": "signup"}

    async def test_empty_tasks_execute_is_noop(self) -> None:
        tasks = AgentTasks()
        assert tasks.pending_count == 0
        await tasks.execute()  # Should not raise

    async def test_pending_count(self) -> None:
        tasks = AgentTasks()
        assert tasks.pending_count == 0
        tasks.add_task(lambda: None)
        assert tasks.pending_count == 1
        tasks.add_task(lambda: None)
        assert tasks.pending_count == 2


class TestAgentTasksInHandler:
    async def test_handler_receives_agent_tasks(self) -> None:
        """Handler with AgentTasks parameter gets an instance injected."""
        executed: list[str] = []

        def log_action(action: str) -> None:
            executed.append(action)

        app = AgenticApp()

        @app.agent_endpoint(name="signup")
        async def handler(intent: Intent, context: AgentContext, tasks: AgentTasks) -> dict[str, str]:
            tasks.add_task(log_action, "send_welcome_email")
            tasks.add_task(log_action, "update_analytics")
            return {"status": "signed up"}

        response = await app.process_intent("sign up new user", endpoint_name="signup")

        assert response.status == "completed"
        assert response.result == {"status": "signed up"}
        # Background tasks should have executed
        assert executed == ["send_welcome_email", "update_analytics"]

    async def test_handler_without_tasks_still_works(self) -> None:
        """Handlers without AgentTasks parameter work normally."""
        app = AgenticApp()

        @app.agent_endpoint(name="simple")
        async def handler(intent: Intent, context: AgentContext) -> dict[str, int]:
            return {"count": 42}

        response = await app.process_intent("count items", endpoint_name="simple")
        assert response.result == {"count": 42}

    async def test_tasks_execute_via_http(self) -> None:
        """Background tasks run when endpoint is called via HTTP."""
        executed: list[str] = []

        app = AgenticApp()

        @app.agent_endpoint(name="order")
        async def handler(intent: Intent, context: AgentContext, tasks: AgentTasks) -> dict[str, str]:
            tasks.add_task(lambda: executed.append("notified"))
            return {"order": "created"}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/agent/order", json={"intent": "create order"})

        assert response.status_code == 200
        assert executed == ["notified"]

    async def test_sync_handler_with_tasks(self) -> None:
        """Sync handlers can also use AgentTasks."""
        executed: list[str] = []

        app = AgenticApp()

        @app.agent_endpoint(name="sync")
        def handler(intent: Intent, context: AgentContext, tasks: AgentTasks) -> dict[str, str]:
            tasks.add_task(lambda: executed.append("done"))
            return {"ok": "true"}

        response = await app.process_intent("do something", endpoint_name="sync")
        assert response.status == "completed"
        assert executed == ["done"]
