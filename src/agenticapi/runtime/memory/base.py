"""Agent memory primitives (Phase C1).

Why memory is a first-class runtime abstraction.

    Every team that deploys an agent eventually bolts on some form of
    persistent memory — user preferences, prior decisions, cached
    reasoning. Today they each write their own: one uses Redis, one
    uses Postgres, one uses a dict on disk. Phase C1 makes memory a
    runtime abstraction on the same footing as
    :class:`~agenticapi.runtime.llm.base.LLMBackend`,
    :class:`~agenticapi.runtime.tools.base.Tool`, and
    :class:`~agenticapi.harness.sandbox.base.SandboxRuntime` so the
    plumbing is shared and the storage backend is a pluggable
    decision instead of a recurring reinvention.

What lands in C1.

    * :class:`MemoryRecord` — the Pydantic row. Carries a scope key
      (``"user:alice"`` / ``"session:abc"`` / ``"global"``), a
      logical key, a JSON-serialisable value, a ``kind``
      discriminator (``episodic`` / ``semantic`` / ``procedural``),
      and a timestamp so consumers can reason about recency.
    * :class:`MemoryStore` — small ``Protocol`` every backend
      satisfies. Operations: ``put``, ``get``, ``search``,
      ``forget``.
    * :class:`InMemoryMemoryStore` — dict-backed, used in tests and
      short-lived dev loops.
    * :class:`SqliteMemoryStore` (in :mod:`sqlite_store`) — the
      persistent default. One table, stdlib ``sqlite3``, no new
      dependencies.

C2 and C3 land separately.

    * **C2** will add :class:`SemanticMemory` (embedding-based
      retrieval) as a second implementation of the same protocol.
    * **C3** will land :class:`MemoryPolicy` (governance + GDPR
      Article 17 scoped forget). The :meth:`MemoryStore.forget`
      primitive below is the contract that lets C3 be implemented
      without a schema migration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class MemoryKind(StrEnum):
    """Discriminator for what *kind* of memory a record holds.

    Taxonomy borrowed from cognitive psychology because it maps
    cleanly onto the three patterns agents actually use:

    * :attr:`EPISODIC` — **what happened.** Conversation turns, tool
      call results, errors. Useful for "what did the user ask me
      last time".
    * :attr:`SEMANTIC` — **what we know.** Facts about the user or
      the world: currency preference, default timezone, favourite
      product category. Usually long-lived.
    * :attr:`PROCEDURAL` — **how we did it.** Cached plans /
      approved code / successful tool chains. Useful for skipping
      the LLM entirely on a familiar request.

    Consumers pick a kind when writing and can filter by kind when
    reading. The enum is a :class:`StrEnum` so existing audit /
    serialisation code treats it as a string without ``.value``.
    """

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryRecord(BaseModel):
    """One row in the memory store.

    Attributes:
        scope: Logical bucket the record belongs to. Recommended
            conventions: ``"user:<id>"``, ``"session:<id>"``,
            ``"endpoint:<name>"``, ``"global"``. Every query /
            forget operation is scope-aware, so using a convention
            here is how GDPR scoped deletion (C3) later works.
        key: Logical key within the scope. Unique per
            ``(scope, key)`` tuple — repeated writes overwrite.
        value: The JSON-serialisable payload. The store serialises
            it via ``json.dumps`` so anything that round-trips
            through stdlib JSON is valid: primitives, lists, dicts,
            nested structures. Pydantic models should be dumped to
            dicts via ``.model_dump()`` before writing.
        kind: Which category of memory this is. See
            :class:`MemoryKind`.
        tags: Free-form tags for coarse filtering. The in-memory and
            sqlite stores use these to build substring searches.
        timestamp: When the record was written. Set automatically to
            the current UTC time when the caller doesn't supply one,
            so the normal flow stays ``MemoryRecord(scope=..., key=..., value=...)``.
        updated_at: Last-modified timestamp. Updated on every
            ``put`` of an existing ``(scope, key)`` pair, which is
            how the store implements LRU semantics for eviction
            later (C3 or ops use cases).
    """

    model_config = ConfigDict(extra="forbid")

    scope: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: Any
    kind: MemoryKind = MemoryKind.SEMANTIC
    tags: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol that every memory backend satisfies.

    Four operations, all async so backends can do real I/O:

    * :meth:`put` — write a record, overwriting any existing
      record with the same ``(scope, key)`` tuple. Bumps the
      ``updated_at`` timestamp on overwrite.
    * :meth:`get` — look up a single record by
      ``(scope, key)``. Returns ``None`` when missing.
    * :meth:`search` — scoped query with optional filters
      (``kind``, ``key_prefix``, ``tag``). Returns a list, in
      reverse-chronological order of ``updated_at``, capped at
      ``limit``.
    * :meth:`forget` — scoped deletion. Returns the number of
      rows removed. Used both for normal "clear this key"
      operations (pass a key) and for GDPR Article 17 "forget
      everything we know about this user" (omit the key — the
      entire scope is dropped).

    Implementations are free to be sync internally (the default
    SQLite store uses blocking ``sqlite3`` under
    :func:`asyncio.to_thread`); the protocol is async so multi-host
    backends drop in without rewiring callers.
    """

    async def put(self, record: MemoryRecord) -> None:
        """Persist a record, overwriting any existing ``(scope, key)`` row."""
        ...

    async def get(self, *, scope: str, key: str) -> MemoryRecord | None:
        """Return a single record or ``None`` if not found."""
        ...

    async def search(
        self,
        *,
        scope: str,
        kind: MemoryKind | None = None,
        key_prefix: str | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        """Return records in ``scope`` matching the optional filters."""
        ...

    async def forget(self, *, scope: str, key: str | None = None) -> int:
        """Hard-delete records. Returns the number of rows removed.

        When ``key`` is ``None``, the *entire* scope is dropped —
        the GDPR Article 17 primitive. Callers that want soft
        deletion or tombstoning should wrap this behind their own
        abstraction; the protocol itself only knows "gone".
        """
        ...


# ---------------------------------------------------------------------------
# In-memory reference implementation
# ---------------------------------------------------------------------------


class InMemoryMemoryStore:
    """Simple dict-backed :class:`MemoryStore` for tests and dev loops.

    Stores records in a ``{(scope, key): MemoryRecord}`` dict. No
    lock because the single-process test shape is always cooperative
    (no preemption). A production multi-host or multi-writer
    backend should use :class:`SqliteMemoryStore` or a Redis /
    Postgres implementation built on the same protocol.

    This class exists primarily so tests can write ``MemoryStore()``
    without importing the SQLite layer, and so the docstrings /
    examples in the rest of the framework have a simple referent.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], MemoryRecord] = {}

    async def put(self, record: MemoryRecord) -> None:
        key = (record.scope, record.key)
        existing = self._records.get(key)
        now = datetime.now(tz=UTC)
        if existing is not None:
            # Preserve the original timestamp but update ``updated_at``
            # so LRU / "most recent" queries surface this write.
            record = record.model_copy(update={"timestamp": existing.timestamp, "updated_at": now})
        else:
            record = record.model_copy(update={"updated_at": now})
        self._records[key] = record

    async def get(self, *, scope: str, key: str) -> MemoryRecord | None:
        return self._records.get((scope, key))

    async def search(
        self,
        *,
        scope: str,
        kind: MemoryKind | None = None,
        key_prefix: str | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        results: list[MemoryRecord] = []
        for (record_scope, record_key), record in self._records.items():
            if record_scope != scope:
                continue
            if kind is not None and record.kind != kind:
                continue
            if key_prefix is not None and not record_key.startswith(key_prefix):
                continue
            if tag is not None and tag not in record.tags:
                continue
            results.append(record)
        results.sort(key=lambda r: r.updated_at, reverse=True)
        return results[:limit]

    async def forget(self, *, scope: str, key: str | None = None) -> int:
        if key is None:
            to_drop = [k for k in self._records if k[0] == scope]
        else:
            to_drop = [(scope, key)] if (scope, key) in self._records else []
        for k in to_drop:
            self._records.pop(k, None)
        return len(to_drop)


__all__ = [
    "InMemoryMemoryStore",
    "MemoryKind",
    "MemoryRecord",
    "MemoryStore",
]
