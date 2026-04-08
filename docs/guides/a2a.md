# Agent-to-Agent Communication

Foundation types for inter-agent communication with capability discovery and trust scoring.

## Capabilities

```python
from agenticapi.interface.a2a import Capability, CapabilityRegistry

registry = CapabilityRegistry()
registry.register(Capability(
    name="inventory_lookup",
    description="Look up current inventory levels",
    sla_max_latency_ms=500,
    sla_availability=0.999,
))

registry.has("inventory_lookup")       # True
registry.get("inventory_lookup")       # Capability object
registry.list_capabilities()           # All registered capabilities
```

## Trust Scoring

```python
from agenticapi.interface.a2a import TrustPolicy, TrustScorer

scorer = TrustScorer(policy=TrustPolicy(
    initial_trust=0.5,
    min_trust_for_read=0.3,
    min_trust_for_write=0.8,
))

scorer.get_score("agent-123")      # 0.5 (initial)
scorer.record_success("agent-123") # Trust increases
scorer.record_failure("agent-123") # Trust decreases
scorer.can_read("agent-123")       # True/False
scorer.can_write("agent-123")      # True/False
```

## Message Types

The A2A protocol defines 10 message types:

`DISCOVER`, `INTENT`, `NEGOTIATE`, `DELEGATE`, `OBSERVE`, `REVISE`, `EXPLAIN`, `VERIFY`, `RESPONSE`, `ERROR`

```python
from agenticapi.interface.a2a import A2AMessage, A2AMessageType

msg = A2AMessage(
    message_type=A2AMessageType.INTENT,
    sender="agent-a",
    receiver="agent-b",
    payload={"action": "read"},
)
```

## Capability Discovery Endpoint

Every app exposes `GET /capabilities` returning structured metadata about all registered endpoints.
