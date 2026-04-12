"""Agent memory runtime (Phase C1).

First-class memory abstraction mirroring
:class:`~agenticapi.runtime.llm.base.LLMBackend` and
:class:`~agenticapi.runtime.tools.base.Tool`: a small protocol +
the common implementations users can pick up without wiring up
their own storage layer.

Re-exports:

* :class:`MemoryRecord` — the typed row
* :class:`MemoryStore` — the protocol every backend satisfies
* :class:`InMemoryMemoryStore` — dict-backed store for tests and
  short-lived dev loops
* :class:`SqliteMemoryStore` — the persistent default, built on
  the stdlib ``sqlite3`` module with the same ``asyncio.to_thread``
  pattern as :class:`~agenticapi.harness.audit.SqliteAuditRecorder`
"""

from __future__ import annotations

from agenticapi.runtime.memory.base import (
    InMemoryMemoryStore,
    MemoryKind,
    MemoryRecord,
    MemoryStore,
)
from agenticapi.runtime.memory.sqlite_store import SqliteMemoryStore

__all__ = [
    "InMemoryMemoryStore",
    "MemoryKind",
    "MemoryRecord",
    "MemoryStore",
    "SqliteMemoryStore",
]
