"""Background task support for agent endpoints.

Provides AgentTasks, analogous to FastAPI's BackgroundTasks. Handlers
receive an AgentTasks instance and add callables that execute after
the HTTP response is sent.

Usage:
    @app.agent_endpoint(name="orders")
    async def order_handler(intent: Intent, context: AgentContext, tasks: AgentTasks):
        tasks.add_task(send_notification, user_id=123, message="Order processed")
        tasks.add_task(update_analytics, action="order_created")
        return {"order_id": 1}

    # send_notification and update_analytics run AFTER the response is sent.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import structlog

logger = structlog.get_logger(__name__)


class AgentTasks:
    """Accumulator for background tasks that run after the response is sent.

    Analogous to FastAPI's ``BackgroundTasks``. Agent endpoint handlers
    receive an ``AgentTasks`` instance as a parameter and call
    ``add_task()`` to schedule work that should happen after the HTTP
    response is returned to the client.

    Tasks execute sequentially in the order they were added. If a task
    fails, subsequent tasks still execute (errors are logged).

    Example:
        async def send_email(to: str, subject: str) -> None:
            ...

        @app.agent_endpoint(name="signup")
        async def signup(intent: Intent, context: AgentContext, tasks: AgentTasks):
            tasks.add_task(send_email, to="user@example.com", subject="Welcome!")
            return {"status": "signed up"}
    """

    def __init__(self) -> None:
        """Initialize an empty task list."""
        self._tasks: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []

    def add_task(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Schedule a background task.

        The task will execute after the HTTP response is sent.
        Both sync and async callables are supported.

        Args:
            func: The callable to execute. Can be sync or async.
            *args: Positional arguments for the callable.
            **kwargs: Keyword arguments for the callable.
        """
        self._tasks.append((func, args, kwargs))

    async def execute(self) -> None:
        """Execute all accumulated tasks sequentially.

        Called by the framework after the response is sent. Individual
        task failures are logged but do not prevent subsequent tasks
        from running.
        """
        for func, args, kwargs in self._tasks:
            try:
                result = func(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "background_task_failed",
                    task=getattr(func, "__name__", str(func)),
                    error=str(exc),
                )

    @property
    def pending_count(self) -> int:
        """Number of tasks waiting to execute."""
        return len(self._tasks)
