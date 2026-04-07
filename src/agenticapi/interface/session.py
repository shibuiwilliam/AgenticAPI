"""Session management for multi-turn agent conversations.

Provides in-memory session storage with TTL-based expiration,
supporting multi-turn conversation tracking and context accumulation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from agenticapi.exceptions import SessionError

logger = structlog.get_logger(__name__)

_DEFAULT_TTL_SECONDS = 1800  # 30 minutes


@dataclass(slots=True)
class Session:
    """A user session for multi-turn agent conversations.

    Tracks conversation history and accumulated context across
    multiple turns. Sessions expire after a configurable TTL.

    Attributes:
        session_id: Unique identifier for this session.
        created_at: When the session was created.
        last_accessed: When the session was last accessed.
        context: Accumulated context dictionary from prior turns.
        history: List of conversation turn records.
        ttl_seconds: Time-to-live in seconds before expiration.
    """

    session_id: str
    created_at: datetime
    last_accessed: datetime
    context: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    ttl_seconds: int = _DEFAULT_TTL_SECONDS

    def add_turn(self, *, intent_raw: str, response_summary: str) -> None:
        """Record a conversation turn in the session history.

        Also updates the last_accessed timestamp.

        Args:
            intent_raw: The raw user request for this turn.
            response_summary: A summary of the agent's response.
        """
        self.last_accessed = datetime.now(tz=UTC)
        self.history.append(
            {
                "intent": intent_raw,
                "response": response_summary,
                "timestamp": self.last_accessed.isoformat(),
            }
        )

    @property
    def is_expired(self) -> bool:
        """Whether this session has exceeded its TTL."""
        elapsed = datetime.now(tz=UTC) - self.last_accessed
        return elapsed > timedelta(seconds=self.ttl_seconds)

    @property
    def turn_count(self) -> int:
        """Number of conversation turns in this session."""
        return len(self.history)


class SessionManager:
    """In-memory session manager with TTL-based expiration.

    Manages creation, retrieval, update, and deletion of sessions.
    Sessions are stored in a simple dictionary keyed by session ID.

    Example:
        manager = SessionManager(ttl_seconds=1800)
        session = await manager.get_or_create(None)  # Creates new
        session.add_turn(intent_raw="hello", response_summary="hi")
        await manager.update(session)
    """

    _CLEANUP_INTERVAL = 100  # Run cleanup every N get_or_create calls

    def __init__(self, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        """Initialize the session manager.

        Args:
            ttl_seconds: Default TTL for new sessions in seconds.
        """
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, Session] = {}
        self._access_count = 0

    async def get_or_create(self, session_id: str | None) -> Session:
        """Get an existing session or create a new one.

        If session_id is None, a new session is always created.
        If the session exists but is expired, it is deleted and a
        new one is created with the same ID.

        Args:
            session_id: The session ID to look up, or None for a new session.

        Returns:
            The existing or newly created Session.
        """
        # Periodically clean up expired sessions to prevent memory leaks
        self._access_count += 1
        if self._access_count % self._CLEANUP_INTERVAL == 0:
            self._cleanup_expired()

        if session_id is not None:
            existing = self._sessions.get(session_id)
            if existing is not None:
                if existing.is_expired:
                    logger.info("session_expired", session_id=session_id)
                    del self._sessions[session_id]
                else:
                    existing.last_accessed = datetime.now(tz=UTC)
                    return existing

        # Create new session
        new_id = session_id if session_id is not None else uuid.uuid4().hex
        now = datetime.now(tz=UTC)
        session = Session(
            session_id=new_id,
            created_at=now,
            last_accessed=now,
            ttl_seconds=self._ttl_seconds,
        )
        self._sessions[new_id] = session

        logger.info("session_created", session_id=new_id)
        return session

    async def get(self, session_id: str) -> Session | None:
        """Get an existing session by ID.

        Returns None if the session does not exist or is expired.

        Args:
            session_id: The session ID to look up.

        Returns:
            The Session if found and not expired, otherwise None.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired:
            del self._sessions[session_id]
            return None
        return session

    async def update(self, session: Session) -> None:
        """Update a session in the store.

        Args:
            session: The session to update.

        Raises:
            SessionError: If the session is not found in the store.
        """
        if session.session_id not in self._sessions:
            raise SessionError(f"Session '{session.session_id}' not found")
        self._sessions[session.session_id] = session

    async def delete(self, session_id: str) -> None:
        """Delete a session from the store.

        Silently succeeds if the session does not exist.

        Args:
            session_id: The session ID to delete.
        """
        self._sessions.pop(session_id, None)
        logger.info("session_deleted", session_id=session_id)

    @property
    def active_count(self) -> int:
        """Number of non-expired sessions currently stored."""
        return sum(1 for s in self._sessions.values() if not s.is_expired)

    def _cleanup_expired(self) -> None:
        """Remove all expired sessions from the store.

        Called periodically from get_or_create() to prevent
        memory leaks from unreferenced expired sessions.
        """
        expired_ids = [sid for sid, s in self._sessions.items() if s.is_expired]
        for sid in expired_ids:
            del self._sessions[sid]
        if expired_ids:
            logger.info("sessions_cleanup", removed_count=len(expired_ids))
