# Agent Memory

AgenticAPI treats memory as a first-class runtime abstraction. Instead of each team bolting on its own ad hoc persistence layer, the framework provides a `MemoryStore` protocol and wires it into every handler via `context.memory`.

## Why framework-level memory?

Agent endpoints commonly need to remember user preferences, prior decisions, and cached reasoning across requests. Without a shared abstraction, every team reinvents the same plumbing with different storage backends. `MemoryStore` makes the storage backend a pluggable decision -- the same way `LLMBackend` makes the model provider pluggable.

## Three memory kinds

Records are tagged with a `MemoryKind` discriminator borrowed from cognitive psychology:

| Kind | Purpose | Example |
|---|---|---|
| `episodic` | **What happened.** Conversation turns, tool call results, errors. | "User asked for Q1 revenue last Tuesday" |
| `semantic` | **What we know.** Stable facts about the user or the world. | "User's currency is EUR" |
| `procedural` | **How we did it.** Cached plans, approved code, successful tool chains. | "The query for monthly revenue is SELECT ..." |

Handlers pick a kind when writing and can filter by kind when reading.

## MemoryStore protocol

Every backend satisfies this four-method async protocol:

```python
class MemoryStore(Protocol):
    async def put(self, record: MemoryRecord) -> None: ...
    async def get(self, *, scope: str, key: str) -> MemoryRecord | None: ...
    async def search(
        self, *, scope: str, kind: MemoryKind | None = None,
        key_prefix: str | None = None, tag: str | None = None, limit: int = 100,
    ) -> list[MemoryRecord]: ...
    async def forget(self, *, scope: str, key: str | None = None) -> int: ...
```

- **`put`** -- write or overwrite a record. `(scope, key)` is the primary key.
- **`get`** -- look up a single record. Returns `None` when missing.
- **`search`** -- scoped query with optional filters by kind, key prefix, or tag. Returns results in reverse-chronological order.
- **`forget`** -- hard-delete records. When `key` is `None`, the entire scope is dropped -- the GDPR Article 17 primitive.

## MemoryRecord

Each record is a Pydantic model:

```python
from agenticapi.runtime.memory import MemoryRecord, MemoryKind

record = MemoryRecord(
    scope="user:alice",
    key="currency",
    value="EUR",
    kind=MemoryKind.SEMANTIC,
    tags=["preference", "locale"],
)
```

| Field | Type | Purpose |
|---|---|---|
| `scope` | `str` | Logical bucket. Convention: `"user:<id>"`, `"session:<id>"`, `"global"` |
| `key` | `str` | Logical key within the scope |
| `value` | `Any` | JSON-serialisable payload |
| `kind` | `MemoryKind` | Discriminator (default: `semantic`) |
| `tags` | `list[str]` | Free-form tags for coarse filtering |
| `timestamp` | `datetime` | When the record was created (auto-set) |
| `updated_at` | `datetime` | Last-modified timestamp (auto-updated on overwrite) |

## Two built-in backends

### InMemoryMemoryStore

Dict-backed, for tests and dev loops. No dependencies, no persistence.

```python
from agenticapi.runtime.memory import InMemoryMemoryStore

memory = InMemoryMemoryStore()
```

### SqliteMemoryStore

Persistent, backed by a single SQLite file using the standard library `sqlite3` module. No new dependencies.

```python
from agenticapi.runtime.memory import SqliteMemoryStore

memory = SqliteMemoryStore(path="./memory.sqlite")
```

The schema is one table (`agent_memory`) with `(scope, key)` as the primary key and three indices covering the query shapes the store exposes. Writes are serialised through an `asyncio.Lock`; reads are lock-free.

## Wiring into AgenticApp

Pass a `MemoryStore` to `AgenticApp(memory=...)` and every handler gets access via `context.memory`:

```python
from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.runtime.context import AgentContext
from agenticapi.runtime.memory import MemoryRecord, MemoryKind, SqliteMemoryStore

memory = SqliteMemoryStore(path="./app_memory.sqlite")
app = AgenticApp(title="Memory Demo", memory=memory)


@app.agent_endpoint(name="remember")
async def remember(intent: Intent, context: AgentContext) -> AgentResponse:
    await context.memory.put(MemoryRecord(
        scope="user:alice",
        key="timezone",
        value="Europe/Berlin",
        kind=MemoryKind.SEMANTIC,
        tags=["preference"],
    ))
    return AgentResponse(result={"stored": True})


@app.agent_endpoint(name="recall")
async def recall(intent: Intent, context: AgentContext) -> AgentResponse:
    record = await context.memory.get(scope="user:alice", key="timezone")
    return AgentResponse(result={"timezone": record.value if record else None})
```

```bash
# Store a preference
curl -X POST http://127.0.0.1:8000/agent/remember \
    -H "Content-Type: application/json" \
    -d '{"intent": "Remember my timezone is Europe/Berlin"}'

# Recall it later (even after restart)
curl -X POST http://127.0.0.1:8000/agent/recall \
    -H "Content-Type: application/json" \
    -d '{"intent": "What is my timezone?"}'
```

## Scope-based isolation and GDPR forget

Every query and delete is scoped. Using a convention like `"user:<id>"` for the scope means:

- One user's memory never leaks into another's.
- GDPR Article 17 "right to be forgotten" is a single call:

```python
deleted_count = await context.memory.forget(scope="user:alice")
```

This drops every record in the scope. To delete a single key:

```python
await context.memory.forget(scope="user:alice", key="timezone")
```

## Implementing a custom backend

Any object with the four async methods satisfies the `MemoryStore` protocol -- no inheritance required. For multi-host deployments, implement the protocol backed by Redis, Postgres, or any other shared store.

## Runnable example

See [`examples/21_persistent_memory/app.py`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/21_persistent_memory) -- a personal assistant that demonstrates all three memory kinds, scope-based isolation, tag-based retrieval, and GDPR forget.

```bash
uvicorn examples.21_persistent_memory.app:app --reload
```

See also:

- [Dependency Injection](dependency-injection.md) -- `context.memory` is available alongside other injected parameters
- [Authentication](authentication.md) -- using auth to derive the memory scope per user
- [Harness & Safety](harness.md) -- memory governance via policies
