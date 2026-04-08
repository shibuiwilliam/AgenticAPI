# Ops Agents

Register operational agents for autonomous system management with severity-based autonomy gating.

## Creating an Ops Agent

```python
from agenticapi.ops import OpsAgent, OpsHealthStatus
from agenticapi.types import AutonomyLevel, Severity

class LogAnalyst(OpsAgent):
    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def check_health(self) -> OpsHealthStatus:
        return OpsHealthStatus(healthy=self._running)

agent = LogAnalyst(
    name="log-analyst",
    autonomy=AutonomyLevel.SUPERVISED,
    max_severity=Severity.MEDIUM,
)
app.register_ops_agent(agent)
```

## Lifecycle

- `start()` is called when the app starts
- `stop()` is called when the app shuts down
- `check_health()` is called by the `GET /health` endpoint — ops agent health is included in the response

## Autonomy Gating

```python
agent.can_handle_autonomously(Severity.LOW)       # True
agent.can_handle_autonomously(Severity.CRITICAL)   # False — needs human

# AutonomyLevel.AUTO    -> handles all severities
# AutonomyLevel.MANUAL  -> handles nothing autonomously
# AutonomyLevel.SUPERVISED -> handles up to max_severity
```
