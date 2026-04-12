"""Unit tests for AgentMesh multi-agent orchestration (MESH-1)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from agenticapi import AgenticApp, AgentMesh
from agenticapi.exceptions import BudgetExceeded
from agenticapi.mesh.context import MeshContext, MeshCycleError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_mesh() -> tuple[AgenticApp, AgentMesh]:
    app = AgenticApp(title="Test Mesh")
    mesh = AgentMesh(app=app, name="test")
    return app, mesh


# ---------------------------------------------------------------------------
# Tests: role + orchestrator registration
# ---------------------------------------------------------------------------


class TestMeshRegistration:
    def test_role_registered(self) -> None:
        _app, mesh = _build_mesh()

        @mesh.role(name="greeter")
        async def greeter(payload: str, ctx: MeshContext) -> dict:
            return {"greeting": f"Hello, {payload}!"}

        assert "greeter" in mesh.roles

    def test_duplicate_role_raises(self) -> None:
        _app, mesh = _build_mesh()

        @mesh.role(name="r1")
        async def r1(payload: str, ctx: MeshContext) -> str:
            return "ok"

        with pytest.raises(ValueError, match="already registered"):

            @mesh.role(name="r1")
            async def r1_dup(payload: str, ctx: MeshContext) -> str:
                return "dup"

    def test_orchestrator_registered(self) -> None:
        _app, mesh = _build_mesh()

        @mesh.role(name="worker")
        async def worker(payload: str, ctx: MeshContext) -> str:
            return "done"

        @mesh.orchestrator(name="pipeline", roles=["worker"])
        async def pipeline(intent: object, mesh_ctx: MeshContext) -> dict:
            result = await mesh_ctx.call("worker", "task")
            return {"result": result}

        assert "pipeline" in mesh._orchestrators


# ---------------------------------------------------------------------------
# Tests: MeshContext.call
# ---------------------------------------------------------------------------


class TestMeshContextCall:
    async def test_call_invokes_role(self) -> None:
        _app, mesh = _build_mesh()

        @mesh.role(name="echo")
        async def echo(payload: str, ctx: MeshContext) -> str:
            return f"echo:{payload}"

        ctx = MeshContext(mesh=mesh, trace_id="t1")
        result = await ctx.call("echo", "hello")
        assert result == "echo:hello"

    async def test_unknown_role_raises(self) -> None:
        _app, mesh = _build_mesh()
        ctx = MeshContext(mesh=mesh, trace_id="t1")
        with pytest.raises(ValueError, match="Unknown mesh role"):
            await ctx.call("nonexistent", "x")

    async def test_cycle_detection(self) -> None:
        _app, mesh = _build_mesh()

        @mesh.role(name="a")
        async def role_a(payload: str, ctx: MeshContext) -> str:
            return await ctx.call("b", payload)

        @mesh.role(name="b")
        async def role_b(payload: str, ctx: MeshContext) -> str:
            return await ctx.call("a", payload)  # cycle!

        ctx = MeshContext(mesh=mesh, trace_id="t1")
        with pytest.raises(MeshCycleError, match="Cycle detected"):
            await ctx.call("a", "x")


class TestMeshBudget:
    async def test_budget_exhausted_raises(self) -> None:
        _app, mesh = _build_mesh()

        @mesh.role(name="expensive")
        async def expensive(payload: str, ctx: MeshContext) -> str:
            return "result"

        ctx = MeshContext(mesh=mesh, trace_id="t1", parent_budget_remaining_usd=0.0)
        with pytest.raises(BudgetExceeded):
            await ctx.call("expensive", "x")

    async def test_budget_propagates_to_child(self) -> None:
        _app, mesh = _build_mesh()
        budgets_seen: list[float | None] = []

        @mesh.role(name="observer")
        async def observer(payload: str, ctx: MeshContext) -> str:
            budgets_seen.append(ctx.parent_budget_remaining_usd)
            return "ok"

        ctx = MeshContext(mesh=mesh, trace_id="t1", parent_budget_remaining_usd=5.0)
        await ctx.call("observer", "x")
        assert budgets_seen[0] == 5.0


# ---------------------------------------------------------------------------
# Tests: pipeline end-to-end via HTTP
# ---------------------------------------------------------------------------


class TestMeshEndToEnd:
    def test_two_role_pipeline_via_http(self) -> None:
        app, mesh = _build_mesh()

        @mesh.role(name="researcher")
        async def researcher(payload: str, ctx: MeshContext) -> dict:
            return {"topic": payload, "points": ["a", "b"]}

        @mesh.role(name="reviewer")
        async def reviewer(payload: str, ctx: MeshContext) -> dict:
            return {"approved": True, "feedback": "Good"}

        @mesh.orchestrator(name="pipeline", roles=["researcher", "reviewer"])
        async def pipeline(intent: object, mesh_ctx: MeshContext) -> dict:
            research = await mesh_ctx.call("researcher", getattr(intent, "raw", str(intent)))
            review = await mesh_ctx.call("reviewer", str(research))
            return {"research": research, "review": review}

        client = TestClient(app)

        # Hit the orchestrator endpoint.
        resp = client.post("/agent/pipeline", json={"intent": "quantum computing"})
        assert resp.status_code == 200
        data = resp.json()
        assert "research" in data["result"]
        assert "review" in data["result"]
        assert data["result"]["research"]["topic"] == "quantum computing"
        assert data["result"]["review"]["approved"] is True

    def test_role_exposed_as_standalone_endpoint(self) -> None:
        app, mesh = _build_mesh()

        @mesh.role(name="solo")
        async def solo(payload: str, ctx: MeshContext) -> str:
            return f"solo:{payload}"

        client = TestClient(app)
        resp = client.post("/agent/solo", json={"intent": "test"})
        assert resp.status_code == 200
        assert "solo:test" in resp.json()["result"]
