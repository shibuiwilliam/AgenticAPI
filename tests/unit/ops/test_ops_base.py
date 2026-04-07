"""Tests for OpsAgent base class."""

from __future__ import annotations

from agenticapi.ops.base import OpsAgent, OpsHealthStatus
from agenticapi.types import AutonomyLevel, Severity


class _DummyOpsAgent(OpsAgent):
    """Concrete OpsAgent for testing."""

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def check_health(self) -> OpsHealthStatus:
        return OpsHealthStatus(healthy=self._running)


class TestOpsAgentProperties:
    def test_name(self) -> None:
        agent = _DummyOpsAgent(name="test-agent")
        assert agent.name == "test-agent"

    def test_defaults(self) -> None:
        agent = _DummyOpsAgent(name="a")
        assert agent.autonomy == AutonomyLevel.SUPERVISED
        assert agent.max_severity == Severity.MEDIUM
        assert agent.running is False

    def test_custom_autonomy(self) -> None:
        agent = _DummyOpsAgent(name="a", autonomy=AutonomyLevel.AUTO)
        assert agent.autonomy == AutonomyLevel.AUTO


class TestOpsAgentLifecycle:
    async def test_start_stop(self) -> None:
        agent = _DummyOpsAgent(name="lifecycle")
        assert agent.running is False
        await agent.start()
        assert agent.running is True
        await agent.stop()
        assert agent.running is False

    async def test_health_check(self) -> None:
        agent = _DummyOpsAgent(name="health")
        status = await agent.check_health()
        assert status.healthy is False
        await agent.start()
        status = await agent.check_health()
        assert status.healthy is True


class TestCanHandleAutonomously:
    def test_auto_handles_all(self) -> None:
        agent = _DummyOpsAgent(name="a", autonomy=AutonomyLevel.AUTO)
        assert agent.can_handle_autonomously(Severity.CRITICAL) is True

    def test_manual_handles_none(self) -> None:
        agent = _DummyOpsAgent(name="a", autonomy=AutonomyLevel.MANUAL)
        assert agent.can_handle_autonomously(Severity.LOW) is False

    def test_supervised_respects_max_severity(self) -> None:
        agent = _DummyOpsAgent(
            name="a",
            autonomy=AutonomyLevel.SUPERVISED,
            max_severity=Severity.MEDIUM,
        )
        assert agent.can_handle_autonomously(Severity.LOW) is True
        assert agent.can_handle_autonomously(Severity.MEDIUM) is True
        assert agent.can_handle_autonomously(Severity.HIGH) is False
        assert agent.can_handle_autonomously(Severity.CRITICAL) is False


class TestOpsHealthStatus:
    def test_defaults(self) -> None:
        status = OpsHealthStatus()
        assert status.healthy is True
        assert status.message == ""
        assert status.details == {}

    def test_custom(self) -> None:
        status = OpsHealthStatus(healthy=False, message="down", details={"error": "timeout"})
        assert status.healthy is False
        assert status.message == "down"
        assert status.details == {"error": "timeout"}
