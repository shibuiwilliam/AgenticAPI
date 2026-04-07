"""Tests for Session and SessionManager."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agenticapi.exceptions import SessionError
from agenticapi.interface.session import Session, SessionManager


class TestSession:
    def test_creation(self) -> None:
        now = datetime.now(tz=UTC)
        session = Session(session_id="abc123", created_at=now, last_accessed=now)
        assert session.session_id == "abc123"
        assert session.turn_count == 0
        assert session.context == {}
        assert session.history == []

    def test_add_turn(self) -> None:
        now = datetime.now(tz=UTC)
        session = Session(session_id="abc", created_at=now, last_accessed=now)
        session.add_turn(intent_raw="hello", response_summary="hi there")
        assert session.turn_count == 1
        assert session.history[0]["intent"] == "hello"
        assert session.history[0]["response"] == "hi there"
        assert "timestamp" in session.history[0]

    def test_add_turn_updates_last_accessed(self) -> None:
        old_time = datetime.now(tz=UTC) - timedelta(minutes=5)
        session = Session(session_id="abc", created_at=old_time, last_accessed=old_time)
        session.add_turn(intent_raw="test", response_summary="ok")
        assert session.last_accessed > old_time

    def test_is_expired_false_when_fresh(self) -> None:
        now = datetime.now(tz=UTC)
        session = Session(session_id="abc", created_at=now, last_accessed=now, ttl_seconds=1800)
        assert session.is_expired is False

    def test_is_expired_true_when_old(self) -> None:
        old_time = datetime.now(tz=UTC) - timedelta(seconds=2000)
        session = Session(session_id="abc", created_at=old_time, last_accessed=old_time, ttl_seconds=1800)
        assert session.is_expired is True

    def test_is_expired_with_short_ttl(self) -> None:
        old_time = datetime.now(tz=UTC) - timedelta(seconds=2)
        session = Session(session_id="abc", created_at=old_time, last_accessed=old_time, ttl_seconds=1)
        assert session.is_expired is True


class TestSessionManager:
    async def test_get_or_create_new(self) -> None:
        manager = SessionManager()
        session = await manager.get_or_create(None)
        assert session.session_id is not None
        assert len(session.session_id) > 0

    async def test_get_or_create_returns_existing(self) -> None:
        manager = SessionManager()
        session1 = await manager.get_or_create(None)
        session2 = await manager.get_or_create(session1.session_id)
        assert session1.session_id == session2.session_id

    async def test_get_or_create_with_specific_id(self) -> None:
        manager = SessionManager()
        session = await manager.get_or_create("my-session-id")
        assert session.session_id == "my-session-id"

    async def test_get_existing_session(self) -> None:
        manager = SessionManager()
        created = await manager.get_or_create("test-id")
        found = await manager.get("test-id")
        assert found is not None
        assert found.session_id == created.session_id

    async def test_get_nonexistent_returns_none(self) -> None:
        manager = SessionManager()
        result = await manager.get("nonexistent")
        assert result is None

    async def test_get_expired_returns_none(self) -> None:
        manager = SessionManager(ttl_seconds=1)
        session = await manager.get_or_create("exp-id")
        # Manually expire the session
        session.last_accessed = datetime.now(tz=UTC) - timedelta(seconds=10)
        result = await manager.get("exp-id")
        assert result is None

    async def test_update(self) -> None:
        manager = SessionManager()
        session = await manager.get_or_create("upd-id")
        session.add_turn(intent_raw="test", response_summary="ok")
        await manager.update(session)
        retrieved = await manager.get("upd-id")
        assert retrieved is not None
        assert retrieved.turn_count == 1

    async def test_update_nonexistent_raises(self) -> None:
        manager = SessionManager()
        now = datetime.now(tz=UTC)
        fake_session = Session(session_id="fake", created_at=now, last_accessed=now)
        with pytest.raises(SessionError, match="not found"):
            await manager.update(fake_session)

    async def test_delete(self) -> None:
        manager = SessionManager()
        await manager.get_or_create("del-id")
        await manager.delete("del-id")
        result = await manager.get("del-id")
        assert result is None

    async def test_delete_nonexistent_silent(self) -> None:
        manager = SessionManager()
        await manager.delete("does-not-exist")  # Should not raise

    async def test_active_count(self) -> None:
        manager = SessionManager()
        await manager.get_or_create("s1")
        await manager.get_or_create("s2")
        assert manager.active_count == 2


class TestSessionCleanup:
    async def test_cleanup_removes_expired(self) -> None:
        manager = SessionManager(ttl_seconds=1)
        session = await manager.get_or_create("expire-me")
        # Manually expire
        session.last_accessed = datetime.now(tz=UTC) - timedelta(seconds=10)

        manager._cleanup_expired()
        assert await manager.get("expire-me") is None

    async def test_cleanup_interval_triggers(self) -> None:
        """Cleanup should run every _CLEANUP_INTERVAL calls to get_or_create."""
        manager = SessionManager(ttl_seconds=1)
        # Use a small interval for testing
        manager._CLEANUP_INTERVAL = 5  # type: ignore[assignment]

        # Create a session and expire it
        session = await manager.get_or_create("old")
        session.last_accessed = datetime.now(tz=UTC) - timedelta(seconds=10)

        # Make enough get_or_create calls to trigger cleanup
        for i in range(5):
            await manager.get_or_create(f"new-{i}")

        # The expired session should have been cleaned up
        assert await manager.get("old") is None

    async def test_cleanup_preserves_active(self) -> None:
        manager = SessionManager(ttl_seconds=3600)
        await manager.get_or_create("active")
        manager._cleanup_expired()
        assert await manager.get("active") is not None
