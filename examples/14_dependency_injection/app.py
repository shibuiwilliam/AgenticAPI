"""Dependency Injection example: a small bookstore API.

Demonstrates AgenticAPI's ``Depends()`` system end-to-end. Where the
other examples wire resources up at module level, this app shows how
to inject fresh resources **per request** with proper setup and
teardown — exactly the pattern you want for database connections,
caches, and external API clients in production.

Features demonstrated:

- ``Depends()`` with **async generator teardown** — connection acquired
  on entry, released on exit, even when the handler raises.
- **Nested dependencies** — ``get_book_repo`` depends on ``get_db`` and
  ``get_cache`` and is itself a dependency of the handler. The
  framework resolves the chain transparently.
- **Per-request caching** — calling the same dependency twice in one
  request returns the same value (``use_cache=True`` is the default).
- **Fresh-per-call dependencies** — ``Depends(generate_request_id,
  use_cache=False)`` runs every reference for a unique value.
- **Route-level dependencies** — ``dependencies=[Depends(rate_limit),
  Depends(audit_log)]`` for cross-cutting concerns whose return values
  don't need to reach the handler.
- **The @tool decorator** — turn a plain function into a registered
  AgenticAPI tool with auto-generated JSON schema.
- **Mixing built-in injectables and Depends()** — handlers can accept
  ``Intent``, ``AgentContext`` *and* ``Depends`` values in the same
  signature, in any order.
- **Composition with Authenticator** — auth runs before dep resolution
  and stashes the ``AuthUser`` in ``context.metadata``, so handlers
  see both the resolved user and their injected dependencies.

Compared to other examples this one deliberately uses **no LLM** so
the focus stays on the dependency-injection mechanics.

Run with:
    uvicorn examples.14_dependency_injection.app:app --reload

Test with curl:
    # List books — uses Depends(get_book_repo) which itself depends
    # on Depends(get_db) and Depends(get_cache) (nested chain).
    curl -X POST http://127.0.0.1:8000/agent/books.list \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "List all books"}'

    # Get a single book — composes get_book_repo with the @tool
    # decorator (search_books_by_author).
    curl -X POST http://127.0.0.1:8000/agent/books.detail \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show book with id 2"}'

    # Authenticated endpoint — Authenticator extracts the user id
    # from X-User-Id, then the handler reads context.metadata["auth_user"]
    # and combines it with Depends(get_book_repo).
    curl -X POST http://127.0.0.1:8000/agent/books.recommend \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: 1" \\
        -d '{"intent": "Recommend a book for me"}'

    # Order endpoint — exercises route-level dependencies
    # (rate_limit + audit_log) and a fresh-per-call request_id.
    curl -X POST http://127.0.0.1:8000/agent/books.order \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: 2" \\
        -d '{"intent": "Order book 3"}'

    # Inspect the audit log — proves the route-level audit_log
    # dependency ran for previous calls.
    curl -X POST http://127.0.0.1:8000/agent/admin.audit_trail \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show audit trail"}'

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agenticapi import AgenticApp, Depends, tool
from agenticapi.routing import AgentRouter
from agenticapi.security import (
    APIKeyHeader,
    AuthCredentials,
    Authenticator,
    AuthUser,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# 1. In-memory "database" — stand-in for a real connection pool
# ---------------------------------------------------------------------------
#
# In production, replace this with SQLAlchemy, asyncpg, etc. The point is
# that the resources are acquired *per request* via Depends() rather than
# instantiated at import time.

BOOKS: list[dict[str, Any]] = [
    {"id": 1, "title": "The Pragmatic Programmer", "author": "Hunt & Thomas", "price": 39.99, "stock": 12},
    {"id": 2, "title": "Designing Data-Intensive Applications", "author": "Kleppmann", "price": 49.99, "stock": 5},
    {"id": 3, "title": "Clean Code", "author": "Martin", "price": 34.99, "stock": 8},
    {"id": 4, "title": "Refactoring", "author": "Fowler", "price": 44.99, "stock": 3},
    {"id": 5, "title": "Domain-Driven Design", "author": "Evans", "price": 54.99, "stock": 0},
]

USERS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "name": "Alice", "favorite_genres": ["software-engineering", "architecture"]},
    2: {"id": 2, "name": "Bob", "favorite_genres": ["refactoring"]},
}

ORDERS: list[dict[str, Any]] = []
AUDIT_LOG: list[dict[str, Any]] = []
RATE_LIMIT_BUCKET: dict[str, list[float]] = {}


class FakeDBConnection:
    """Stand-in for a real DB connection. Tracks open/close for the demo."""

    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.opened_at = time.monotonic()
        self.closed = False
        self.queries: list[str] = []

    async def fetch_all_books(self) -> list[dict[str, Any]]:
        self.queries.append("SELECT * FROM books")
        return [dict(b) for b in BOOKS]

    async def fetch_book(self, book_id: int) -> dict[str, Any] | None:
        self.queries.append(f"SELECT * FROM books WHERE id = {book_id}")
        for b in BOOKS:
            if b["id"] == book_id:
                return dict(b)
        return None

    async def insert_order(self, user_id: int, book_id: int) -> dict[str, Any]:
        self.queries.append(f"INSERT INTO orders (user_id, book_id) VALUES ({user_id}, {book_id})")
        order = {
            "id": len(ORDERS) + 1,
            "user_id": user_id,
            "book_id": book_id,
            "created_at": datetime.now(UTC).isoformat(),
        }
        ORDERS.append(order)
        return order

    async def close(self) -> None:
        self.closed = True


class FakeCache:
    """Per-request cache. Cleared when the dependency is torn down."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value


class BookRepository:
    """A thin repo wrapper. Built on top of a FakeDBConnection.

    Used to demonstrate **nested dependencies**: ``get_book_repo`` takes
    ``Depends(get_db)`` and ``Depends(get_cache)``, then exposes a
    higher-level interface to handlers. Handlers depend on the repo,
    never on the raw connection.
    """

    def __init__(self, db: FakeDBConnection, cache: FakeCache) -> None:
        self._db = db
        self._cache = cache

    @property
    def db_connection_id(self) -> str:
        return self._db.id

    @property
    def cache_stats(self) -> dict[str, int]:
        return {"hits": self._cache.hits, "misses": self._cache.misses}

    async def list_books(self) -> list[dict[str, Any]]:
        cached = self._cache.get("all_books")
        if cached is not None:
            return cached
        rows = await self._db.fetch_all_books()
        self._cache.set("all_books", rows)
        return rows

    async def get_book(self, book_id: int) -> dict[str, Any] | None:
        return await self._db.fetch_book(book_id)

    async def place_order(self, user_id: int, book_id: int) -> dict[str, Any]:
        return await self._db.insert_order(user_id, book_id)


# ---------------------------------------------------------------------------
# 2. Dependency providers
# ---------------------------------------------------------------------------
#
# Each function below is a dependency. The framework calls them once per
# request (because use_cache defaults to True), passes the result to any
# handler that declares ``Depends(provider)``, and runs the teardown
# (whatever follows ``yield``) after the response is built.


async def get_db() -> AsyncIterator[FakeDBConnection]:
    """Open a fresh DB connection for the request and close it on teardown.

    This is the canonical pattern for any resource that needs cleanup.
    The yield value is what gets injected into the handler. Anything
    after ``yield`` runs after the handler returns — even if the handler
    raises.
    """
    conn = FakeDBConnection()
    try:
        yield conn
    finally:
        await conn.close()


async def get_cache() -> FakeCache:
    """Provide a per-request in-memory cache (no teardown needed).

    Plain async function — no yield. The framework treats it the same
    as the generator form except there's nothing to clean up.
    """
    return FakeCache()


async def get_book_repo(
    db: FakeDBConnection = Depends(get_db),
    cache: FakeCache = Depends(get_cache),
) -> BookRepository:
    """A nested dependency: takes two other ``Depends()`` values.

    The framework resolves the chain transparently — handlers that
    declare ``Depends(get_book_repo)`` never see the underlying db
    or cache, they just get a ready-to-use repository.

    Because of per-request caching, if the same handler also asked
    for ``Depends(get_db)`` directly, it would receive the **same**
    connection instance that this provider used to build the repo.
    """
    return BookRepository(db=db, cache=cache)


def generate_request_id() -> str:
    """Return a fresh ID. Used with ``use_cache=False`` so every reference
    in a single request gets a different value.
    """
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# 3. Route-level dependencies — cross-cutting side effects
# ---------------------------------------------------------------------------
#
# These run before the handler, in declared order. Their return values
# are discarded — they exist purely for side effects (rate limiting,
# audit logging, schema migration checks, etc). They keep the handler
# signature clean: the handler doesn't need to know they exist.
#
# Route-level dependency providers in AgenticAPI take no parameters
# (or only nested ``Depends()`` values). Anything they need from the
# request is read from module-level state, contextvars, or other
# nested dependencies.


async def rate_limit() -> None:
    """Allow at most 10 requests per minute globally.

    A real implementation would key on user/IP from a contextvar set
    upstream; for the demo we use a single global window so the rate
    limit is observable from a curl session.
    """
    now = time.monotonic()
    window = RATE_LIMIT_BUCKET.setdefault("global", [])
    while window and window[0] < now - 60:
        window.pop(0)
    if len(window) >= 10:
        raise PermissionError("Rate limit exceeded (10 requests per minute)")
    window.append(now)


async def audit_log() -> None:
    """Record that a sensitive endpoint was hit."""
    AUDIT_LOG.append(
        {
            "ts": datetime.now(UTC).isoformat(),
            "endpoint": "books.order",
            "trace": uuid.uuid4().hex[:8],
        }
    )


# ---------------------------------------------------------------------------
# 4. Authentication — runs BEFORE dep resolution
# ---------------------------------------------------------------------------
#
# AgenticAPI's Authenticator runs in the request lifecycle before any
# Depends() chain. Its result lands in context.metadata["auth_user"],
# where downstream handlers and route-level deps can read it.
#
# Here we use APIKeyHeader as a stand-in for a real auth header — the
# "key" is just a numeric user id. In production this would be a JWT
# or an opaque session token.


async def verify_user_id(credentials: AuthCredentials) -> AuthUser | None:
    """Look up a user by id (the credentials.credentials value)."""
    try:
        user_id = int(credentials.credentials)
    except ValueError:
        return None
    user = USERS.get(user_id)
    if user is None:
        return None
    return AuthUser(
        user_id=str(user["id"]),
        username=user["name"],
        metadata={"favorite_genres": user["favorite_genres"]},
    )


user_auth = Authenticator(
    scheme=APIKeyHeader(name="X-User-Id"),
    verify=verify_user_id,
)


# ---------------------------------------------------------------------------
# 5. Tools — the @tool decorator showcase
# ---------------------------------------------------------------------------


@tool(description="Search the bookstore by author name (case-insensitive substring match).")
async def search_books_by_author(author: str, limit: int = 10) -> list[dict[str, Any]]:
    """Demonstrates the @tool decorator: a plain async function with type
    hints becomes an AgenticAPI Tool with an auto-generated JSON schema.

    Same function still works as a regular Python call — useful for tests.
    """
    needle = author.lower()
    matches = [b for b in BOOKS if needle in b["author"].lower()]
    return matches[:limit]


# ---------------------------------------------------------------------------
# 6. Endpoints
# ---------------------------------------------------------------------------

app = AgenticApp(title="Bookstore (Dependency Injection demo)", version="0.1.0")
books = AgentRouter(prefix="books", tags=["books"])
admin = AgentRouter(prefix="admin", tags=["admin"])


@books.agent_endpoint(
    name="list",
    description="List all books in the catalogue.",
    autonomy_level="auto",
)
async def list_books(
    intent: Intent,
    context: AgentContext,
    repo: BookRepository = Depends(get_book_repo),
) -> dict[str, Any]:
    """Single dependency: ``get_book_repo``.

    The repo internally uses ``Depends(get_db)`` and ``Depends(get_cache)``,
    so even though this handler asks for one dependency, the framework
    resolves a chain of three. The connection id surfaces in the response
    so you can see it's the same instance throughout the request.
    """
    rows = await repo.list_books()
    return {
        "books": rows,
        "count": len(rows),
        "db_connection_id": repo.db_connection_id,
        "cache_stats": repo.cache_stats,
    }


@books.agent_endpoint(
    name="detail",
    description="Get details about a single book and a few of the same author.",
    autonomy_level="auto",
)
async def book_detail(
    intent: Intent,
    repo: BookRepository = Depends(get_book_repo),
) -> dict[str, Any]:
    """Combines a Depends() injection with a @tool-decorated function call.

    The intent.parameters dict is populated by the keyword parser
    (since this app has no LLM). For demo purposes we extract a
    book id from the intent text.
    """
    book_id = _extract_int(intent.raw, default=1)
    book = await repo.get_book(book_id)
    if book is None:
        return {"error": f"book {book_id} not found"}

    # Call the @tool function directly — it's still a normal function
    # in addition to being a registered tool.
    related = await search_books_by_author(author=book["author"], limit=3)

    return {
        "book": book,
        "related_by_author": [r for r in related if r["id"] != book_id],
        "db_connection_id": repo.db_connection_id,
    }


@books.agent_endpoint(
    name="recommend",
    description="Recommend a book for the authenticated user (requires X-User-Id header).",
    autonomy_level="auto",
    auth=user_auth,
)
async def recommend(
    intent: Intent,
    context: AgentContext,
    repo: BookRepository = Depends(get_book_repo),
) -> dict[str, Any]:
    """Combines authentication with dependency injection.

    The Authenticator runs before any ``Depends()`` resolution, so by
    the time this handler is called the AuthUser is already on
    ``context.metadata["auth_user"]``. The handler then asks for a
    repo via ``Depends(get_book_repo)``, which the framework
    resolves through the nested ``get_db`` + ``get_cache`` chain.
    """
    auth_user: AuthUser = context.metadata["auth_user"]
    rows = await repo.list_books()
    in_stock = [b for b in rows if b["stock"] > 0]
    if not in_stock:
        return {"user": auth_user.username, "recommendation": None}
    pick = in_stock[int(auth_user.user_id) % len(in_stock)]
    return {
        "user": auth_user.username,
        "recommendation": pick,
        "db_connection_id": repo.db_connection_id,
    }


@books.agent_endpoint(
    name="order",
    description="Order a book. Rate-limited and audited via route-level dependencies.",
    autonomy_level="supervised",
    auth=user_auth,
    dependencies=[Depends(rate_limit), Depends(audit_log)],
)
async def place_order(
    intent: Intent,
    context: AgentContext,
    repo: BookRepository = Depends(get_book_repo),
    request_id: str = Depends(generate_request_id, use_cache=False),
) -> dict[str, Any]:
    """Showcases the full dependency-injection toolbox.

    - **Authenticator** runs first, populating ``context.metadata["auth_user"]``.
    - **Route-level deps** (``rate_limit``, ``audit_log``) run next for
      side effects only — their return values never reach this function.
    - **Handler-level Depends()** for ``repo`` and ``request_id``.
    - **``use_cache=False``** for ``request_id`` — every reference in
      the same request would produce a fresh value. Useful for
      idempotency keys, correlation IDs, etc.
    """
    auth_user: AuthUser = context.metadata["auth_user"]
    book_id = _extract_int(intent.raw, default=1)
    book = await repo.get_book(book_id)
    if book is None or book["stock"] <= 0:
        return {
            "request_id": request_id,
            "error": f"book {book_id} unavailable",
            "user": auth_user.username,
        }

    order = await repo.place_order(user_id=int(auth_user.user_id), book_id=book_id)
    return {
        "request_id": request_id,
        "order": order,
        "user": auth_user.username,
        "book": book["title"],
    }


@admin.agent_endpoint(
    name="audit_trail",
    description="Show the audit log built up by route-level dependencies.",
    autonomy_level="auto",
)
async def audit_trail(intent: Intent) -> dict[str, Any]:
    """Read-only view onto the in-memory audit log so you can confirm
    that the route-level ``audit_log`` dependency actually ran.
    """
    return {
        "entries": list(AUDIT_LOG),
        "total": len(AUDIT_LOG),
    }


# ---------------------------------------------------------------------------
# 7. Helpers
# ---------------------------------------------------------------------------


def _extract_int(text: str, *, default: int) -> int:
    """Pull the first integer out of a free-text intent (very rough)."""
    digits = ""
    for ch in text:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else default


# ---------------------------------------------------------------------------
# 8. App assembly
# ---------------------------------------------------------------------------

app.include_router(books)
app.include_router(admin)
