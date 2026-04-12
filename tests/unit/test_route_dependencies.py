"""Unit tests for D6 — route-level ``dependencies=[…]``.

Verifies that dependencies declared on the decorator (not in the
handler signature) run for side effects, in declared order, with
exception propagation, and with teardown semantics for generator-style
deps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from agenticapi import AgenticApp, Depends
from agenticapi.exceptions import AuthenticationError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class TestRouteLevelDependencies:
    def test_runs_in_declared_order(self) -> None:
        """Route deps run before the handler in declaration order."""
        log: list[str] = []

        async def first():
            log.append("first")

        async def second():
            log.append("second")

        app = AgenticApp(title="d6")

        @app.agent_endpoint(
            name="ep",
            autonomy_level="auto",
            dependencies=[Depends(first), Depends(second)],
        )
        async def handler(intent, context):
            log.append("handler")
            return {"ok": True}

        client = TestClient(app)
        client.post("/agent/ep", json={"intent": "x"})
        assert log == ["first", "second", "handler"]

    def test_exception_short_circuits_handler(self) -> None:
        """A raising route dep prevents the handler from running."""
        log: list[str] = []

        async def auth_check():
            log.append("auth")
            raise AuthenticationError("nope")

        app = AgenticApp(title="d6")

        @app.agent_endpoint(
            name="ep",
            autonomy_level="auto",
            dependencies=[Depends(auth_check)],
        )
        async def handler(intent, context):
            log.append("handler")
            return {}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/agent/ep", json={"intent": "x"})
        assert response.status_code == 401
        assert "auth" in log
        assert "handler" not in log

    def test_route_deps_in_addition_to_handler_deps(self) -> None:
        """Route deps and handler-signature deps coexist."""
        events: list[str] = []

        async def route_dep():
            events.append("route_dep")

        def get_db() -> str:
            events.append("handler_dep")
            return "db-handle"

        app = AgenticApp(title="d6-mix")

        @app.agent_endpoint(
            name="ep",
            autonomy_level="auto",
            dependencies=[Depends(route_dep)],
        )
        async def handler(intent, context, db: str = Depends(get_db)):
            events.append("handler")
            return {"db": db}

        client = TestClient(app)
        body = client.post("/agent/ep", json={"intent": "x"}).json()
        assert events == ["route_dep", "handler_dep", "handler"]
        assert body["result"]["db"] == "db-handle"

    def test_generator_route_dep_teardown(self) -> None:
        """Generator-style route deps run their teardown after the handler."""
        log: list[str] = []

        async def lifespan_dep() -> AsyncIterator[None]:
            log.append("setup")
            yield
            log.append("teardown")

        app = AgenticApp(title="d6-gen")

        @app.agent_endpoint(
            name="ep",
            autonomy_level="auto",
            dependencies=[Depends(lifespan_dep)],
        )
        async def handler(intent, context):
            log.append("handler")
            return {}

        client = TestClient(app)
        client.post("/agent/ep", json={"intent": "x"})
        assert log == ["setup", "handler", "teardown"]

    @pytest.mark.parametrize("count", [0, 1, 3])
    def test_arbitrary_number_of_deps(self, count: int) -> None:
        """The framework accepts zero, one, or many route deps."""
        log: list[int] = []

        def make_dep(i: int):
            def dep():
                log.append(i)

            return dep

        deps = [Depends(make_dep(i)) for i in range(count)]

        app = AgenticApp(title="d6-n")

        @app.agent_endpoint(name="ep", autonomy_level="auto", dependencies=deps)
        async def handler(intent, context):
            return {}

        client = TestClient(app)
        client.post("/agent/ep", json={"intent": "x"})
        assert log == list(range(count))
