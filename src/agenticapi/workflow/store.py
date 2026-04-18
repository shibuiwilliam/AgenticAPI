"""Workflow state persistence.

Provides the :class:`WorkflowStore` protocol and two reference
implementations for persisting workflow state across checkpoint
pauses and process restarts.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from pathlib import Path


logger = structlog.get_logger(__name__)


@runtime_checkable
class WorkflowStore(Protocol):
    """Protocol for persisting workflow state."""

    async def save(self, workflow_id: str, step_name: str, state_json: str) -> None:
        """Save workflow state at a checkpoint.

        Args:
            workflow_id: Unique workflow execution ID.
            step_name: The step that triggered the checkpoint.
            state_json: JSON-serialised workflow state.
        """
        ...

    async def load(self, workflow_id: str) -> tuple[str, str] | None:
        """Load persisted workflow state.

        Args:
            workflow_id: The workflow execution ID.

        Returns:
            A ``(step_name, state_json)`` tuple, or ``None`` if
            not found.
        """
        ...

    async def delete(self, workflow_id: str) -> None:
        """Remove a persisted workflow.

        Args:
            workflow_id: The workflow execution ID.
        """
        ...

    async def list_active(self) -> list[str]:
        """List all active (paused) workflow IDs.

        Returns:
            Sorted list of workflow IDs.
        """
        ...


class InMemoryWorkflowStore:
    """In-memory workflow store (default, no persistence across restarts)."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, str]] = {}

    async def save(self, workflow_id: str, step_name: str, state_json: str) -> None:
        self._store[workflow_id] = (step_name, state_json)
        logger.info("workflow_state_saved", workflow_id=workflow_id, step=step_name)

    async def load(self, workflow_id: str) -> tuple[str, str] | None:
        return self._store.get(workflow_id)

    async def delete(self, workflow_id: str) -> None:
        self._store.pop(workflow_id, None)

    async def list_active(self) -> list[str]:
        return sorted(self._store.keys())


class SqliteWorkflowStore:
    """SQLite-backed workflow store for production persistence."""

    def __init__(self, *, path: str | Path) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_states (
                workflow_id TEXT PRIMARY KEY,
                step_name   TEXT NOT NULL,
                state_json  TEXT NOT NULL,
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    async def save(self, workflow_id: str, step_name: str, state_json: str) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO workflow_states (workflow_id, step_name, state_json, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (workflow_id, step_name, state_json),
        )
        self._conn.commit()
        logger.info("workflow_state_saved_sqlite", workflow_id=workflow_id, step=step_name)

    async def load(self, workflow_id: str) -> tuple[str, str] | None:
        row = self._conn.execute(
            "SELECT step_name, state_json FROM workflow_states WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchone()
        if row is None:
            return None
        return (row[0], row[1])

    async def delete(self, workflow_id: str) -> None:
        self._conn.execute("DELETE FROM workflow_states WHERE workflow_id = ?", (workflow_id,))
        self._conn.commit()

    async def list_active(self) -> list[str]:
        rows = self._conn.execute("SELECT workflow_id FROM workflow_states ORDER BY workflow_id").fetchall()
        return [row[0] for row in rows]
