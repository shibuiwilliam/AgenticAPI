"""Unit tests for the ``Depends`` marker, scanner, and solver.

Covers the public surface of ``agenticapi.dependencies``: scanning a
handler signature, resolving sync/async/generator dependencies,
nested dependencies, request-scoped caching, ``dependency_overrides``,
generator teardown, and the cycle-protection guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agenticapi.dependencies import (
    DependencyResolutionError,
    Depends,
    InjectionKind,
    invoke_handler,
    scan_handler,
    solve,
)
from agenticapi.interface.intent import Intent, IntentAction
from agenticapi.interface.tasks import AgentTasks  # noqa: TC001 — used at runtime in handlers
from agenticapi.runtime.context import AgentContext

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


def _intent() -> Intent:
    return Intent(raw="hello", action=IntentAction.READ, domain="test")


def _context() -> AgentContext:
    return AgentContext(trace_id="t1", endpoint_name="ep")


# ---------------------------------------------------------------------------
# scan_handler
# ---------------------------------------------------------------------------


class TestScanHandler:
    def test_legacy_intent_context_signature(self) -> None:
        """The historical ``(intent, context)`` shape stays positional."""

        async def h(intent, context):
            return None

        plan = scan_handler(h)
        assert plan.legacy_positional_count == 2
        assert all(p.kind is InjectionKind.POSITIONAL_LEGACY for p in plan.params)

    def test_typed_intent_context(self) -> None:
        """Annotated parameters are recognised as built-in injectables."""

        async def h(intent: Intent, context: AgentContext) -> None:
            del intent, context

        plan = scan_handler(h)
        kinds = [p.kind for p in plan.params]
        assert InjectionKind.INTENT in kinds
        assert InjectionKind.CONTEXT in kinds
        assert plan.legacy_positional_count == 0

    def test_agent_tasks_recognised(self) -> None:
        """``AgentTasks`` parameter is detected."""

        async def h(intent: Intent, tasks: AgentTasks) -> None:
            del intent, tasks

        plan = scan_handler(h)
        kinds = [p.kind for p in plan.params]
        assert InjectionKind.AGENT_TASKS in kinds

    def test_depends_default_recognised(self) -> None:
        """A ``Depends(...)`` default value becomes a DEPENDS plan entry."""

        async def get_db() -> str:
            return "db-handle"

        async def h(intent: Intent, db: str = Depends(get_db)) -> None:
            del intent, db

        plan = scan_handler(h)
        depends_plans = [p for p in plan.params if p.kind is InjectionKind.DEPENDS]
        assert len(depends_plans) == 1
        assert depends_plans[0].dependency is not None
        assert depends_plans[0].dependency.callable is get_db


# ---------------------------------------------------------------------------
# solve + invoke_handler
# ---------------------------------------------------------------------------


class TestSolveAndInvoke:
    async def test_resolves_sync_dependency(self) -> None:
        """A plain sync dependency is called once and its return injected."""
        call_count = {"n": 0}

        def get_value() -> int:
            call_count["n"] += 1
            return 42

        async def handler(intent: Intent, value: int = Depends(get_value)) -> int:
            del intent
            return value

        plan = scan_handler(handler)
        resolved = await solve(
            plan,
            intent=_intent(),
            context=_context(),
            files=None,
            htmx_scope=None,
            overrides={},
        )
        result = await invoke_handler(handler, resolved)
        assert result == 42
        assert call_count["n"] == 1

    async def test_resolves_async_dependency(self) -> None:
        """An async dependency is awaited."""

        async def get_value() -> str:
            return "async-result"

        async def handler(intent: Intent, value: str = Depends(get_value)) -> str:
            del intent
            return value

        plan = scan_handler(handler)
        resolved = await solve(
            plan,
            intent=_intent(),
            context=_context(),
            files=None,
            htmx_scope=None,
            overrides={},
        )
        assert await invoke_handler(handler, resolved) == "async-result"

    async def test_async_generator_dependency_runs_teardown(self) -> None:
        """Async generator dependency teardown executes after the handler."""
        events: list[str] = []

        async def get_db() -> AsyncIterator[str]:
            events.append("setup")
            yield "session"
            events.append("teardown")

        async def handler(intent: Intent, db: str = Depends(get_db)) -> str:
            del intent
            events.append(f"handler:{db}")
            return db

        plan = scan_handler(handler)
        resolved = await solve(
            plan,
            intent=_intent(),
            context=_context(),
            files=None,
            htmx_scope=None,
            overrides={},
        )
        result = await invoke_handler(handler, resolved)
        assert result == "session"
        assert events == ["setup", "handler:session", "teardown"]

    async def test_sync_generator_dependency_runs_teardown(self) -> None:
        """Sync generator dependency teardown executes after the handler."""
        events: list[str] = []

        def get_resource() -> Iterator[str]:
            events.append("acquire")
            yield "res"
            events.append("release")

        async def handler(intent: Intent, res: str = Depends(get_resource)) -> str:
            del intent
            return res

        plan = scan_handler(handler)
        resolved = await solve(
            plan,
            intent=_intent(),
            context=_context(),
            files=None,
            htmx_scope=None,
            overrides={},
        )
        await invoke_handler(handler, resolved)
        assert events == ["acquire", "release"]

    async def test_request_scoped_cache(self) -> None:
        """The same dependency referenced twice resolves once per request."""
        call_count = {"n": 0}

        def expensive() -> int:
            call_count["n"] += 1
            return 7

        def derived(x: int = Depends(expensive)) -> int:
            return x + 1

        async def handler(
            intent: Intent,
            a: int = Depends(expensive),
            b: int = Depends(derived),
        ) -> tuple[int, int]:
            del intent
            return (a, b)

        plan = scan_handler(handler)
        resolved = await solve(
            plan,
            intent=_intent(),
            context=_context(),
            files=None,
            htmx_scope=None,
            overrides={},
        )
        result = await invoke_handler(handler, resolved)
        assert result == (7, 8)
        assert call_count["n"] == 1

    async def test_dependency_override(self) -> None:
        """``overrides`` map substitutes a dependency callable for a fake."""

        def real_db() -> str:
            return "real"

        def fake_db() -> str:
            return "fake"

        async def handler(intent: Intent, db: str = Depends(real_db)) -> str:
            del intent
            return db

        plan = scan_handler(handler)
        resolved = await solve(
            plan,
            intent=_intent(),
            context=_context(),
            files=None,
            htmx_scope=None,
            overrides={real_db: fake_db},
        )
        assert await invoke_handler(handler, resolved) == "fake"

    async def test_circular_dependency_raises(self) -> None:
        """A self-referential dependency chain raises DependencyResolutionError."""

        # Build a cycle by referencing itself indirectly. Direct
        # self-reference is structurally hard to construct, so we
        # build a chain that exceeds the depth guard.
        def make_chain() -> object:
            # Build N nested Depends — we'll exceed the 32-level cap.
            current_default = Depends(lambda: "leaf")
            for _ in range(40):
                inner = current_default

                def step(x: object = inner) -> object:
                    return x

                current_default = Depends(step)
            return current_default

        async def handler(intent: Intent, x: object = make_chain()) -> object:
            del intent
            return x

        plan = scan_handler(handler)
        with pytest.raises(DependencyResolutionError):
            await solve(
                plan,
                intent=_intent(),
                context=_context(),
                files=None,
                htmx_scope=None,
                overrides={},
            )

    async def test_legacy_positional_handler_still_works(self) -> None:
        """An unannotated ``(intent, context)`` handler runs untouched."""

        async def handler(intent, context):
            return f"{intent.raw}@{context.endpoint_name}"

        plan = scan_handler(handler)
        resolved = await solve(
            plan,
            intent=_intent(),
            context=_context(),
            files=None,
            htmx_scope=None,
            overrides={},
        )
        result = await invoke_handler(handler, resolved)
        assert result == "hello@ep"

    async def test_built_in_injectables_via_solver(self) -> None:
        """``Intent``, ``AgentContext``, and ``AgentTasks`` flow through the solver."""

        async def handler(
            intent: Intent,
            context: AgentContext,
            tasks: AgentTasks,
        ) -> tuple[str, str]:
            del context
            tasks.add_task(lambda: None)
            return (intent.raw, "ok")

        plan = scan_handler(handler)
        resolved = await solve(
            plan,
            intent=_intent(),
            context=_context(),
            files=None,
            htmx_scope=None,
            overrides={},
        )
        assert resolved.tasks is not None
        assert await invoke_handler(handler, resolved) == ("hello", "ok")
        assert resolved.tasks.pending_count == 1
