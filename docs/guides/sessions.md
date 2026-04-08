# Sessions

AgenticAPI supports multi-turn conversations via the `SessionManager`.

## How Sessions Work

Pass a `session_id` in the request body to maintain context across turns:

```bash
# Turn 1
curl -X POST http://127.0.0.1:8000/agent/orders.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show Tokyo orders", "session_id": "sess-123"}'

# Turn 2 — "those" refers to Tokyo orders from turn 1
curl -X POST http://127.0.0.1:8000/agent/orders.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Which of those are overdue?", "session_id": "sess-123"}'
```

## Configuration

```python
from agenticapi.interface.session import SessionManager

# Default: 30-minute TTL, in-memory storage
app = AgenticApp(title="My App")

# The session manager is accessible via:
app.session_manager  # SessionManager instance
app.session_manager.active_count  # Number of active sessions
```

## Session Data

Each `Session` contains:

- `session_id` — Unique identifier
- `context` — Accumulated key-value context
- `history` — List of turn records (intent + response summary)
- `ttl_seconds` — Time-to-live (default 1800 = 30 minutes)
- `turn_count` — Number of conversation turns

Expired sessions are cleaned up automatically.
