"""Persistent Memory example: a personal assistant that never forgets.

Demonstrates AgenticAPI's **first-class memory primitive** (Phase C1)
end-to-end. Memory in an agent app is not "database access" — it's a
primary reasoning input the handler consults on every turn. This
example is the reference for wiring ``SqliteMemoryStore`` into an
``AgenticApp`` and using it from handlers via ``context.memory``.

Where other examples bolt memory onto the side or keep it in a module
global, this app treats memory as the spine of the application: every
endpoint reads or writes to the same store, facts survive restarts,
each user has an isolated scope, and GDPR "right to be forgotten"
ships as one line.

Features demonstrated
---------------------

- ``AgenticApp(memory=SqliteMemoryStore(...))`` — framework-level
  wiring so ``context.memory`` is available in every handler.
- All **three memory kinds** from :class:`MemoryKind`:

  * ``semantic`` — stable facts about the user (name, timezone,
    currency preference, dietary restrictions).
  * ``episodic`` — a rolling log of conversation turns, queryable by
    recency for "what did the user ask last time?"
  * ``procedural`` — reusable "recipes" / saved queries the
    assistant promotes after it has answered a question successfully
    at least once.

- **Scope-based multi-tenant isolation** — every record uses the
  convention ``"user:<id>"`` so one user's memory cannot leak into
  another's, and :meth:`MemoryStore.forget` can drop the whole
  scope in a single call (GDPR Article 17).
- **Cross-request persistence** — the store is a real SQLite file
  on disk, so facts survive a process restart. A test proves this.
- **Tag-based retrieval** — records carry free-form tags
  (``["preference", "dietary"]``) that the assistant filters on
  when it answers a question.
- **Authentication driving memory scope** — an
  ``Authenticator`` resolves the current user, and a tiny helper
  (``_user_scope``) turns ``context.metadata["auth_user"]`` into
  the canonical ``"user:<id>"`` scope every handler reads and
  writes under. Centralising the scope-construction in one place
  is the pattern that makes C3 ``MemoryPolicy`` governance
  additive later — every read/write flows through this helper.
- **Pydantic response models** — every endpoint declares a
  ``response_model=`` so ``/openapi.json`` publishes real schemas
  and the handler return value is validated before it goes out.
- **No LLM required** — the example runs on direct-handler mode,
  which is exactly how most production memory-heavy endpoints are
  built (the interesting work is in the memory choreography, not
  in code generation).

Run
---

::

    uvicorn examples.21_persistent_memory.app:app --reload
    # or
    agenticapi dev --app examples.21_persistent_memory.app:app

The store lives at ``./agenticapi_memory_demo.sqlite`` in the working
directory. Delete it to start fresh.

Walkthrough with curl
---------------------

::

    # Alice registers some preferences (semantic memory)
    curl -X POST http://127.0.0.1:8000/agent/memory.remember \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: alice" \\
        -d '{"intent": "Remember that my currency is EUR and my timezone is Europe/Berlin"}'

    # Alice adds a dietary note — the handler extracts the key/value
    # from the intent text using simple keyword matching
    curl -X POST http://127.0.0.1:8000/agent/memory.remember \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: alice" \\
        -d '{"intent": "Remember that I am vegetarian"}'

    # Alice asks a question — this endpoint uses all three memory kinds
    # (reads semantic for prefs, writes episodic for the turn, and
    # writes procedural when it finds the answer the first time).
    curl -X POST http://127.0.0.1:8000/agent/memory.ask \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: alice" \\
        -d '{"intent": "What is my currency?"}'

    # Alice repeats the question — this time the answer is served
    # from the procedural (recipe) cache and the response_cached flag
    # flips to true.
    curl -X POST http://127.0.0.1:8000/agent/memory.ask \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: alice" \\
        -d '{"intent": "What is my currency?"}'

    # Alice's recent conversation history (episodic memory)
    curl -X POST http://127.0.0.1:8000/agent/memory.history \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: alice" \\
        -d '{"intent": "Show recent history"}'

    # Bob's view — isolated scope, so he sees nothing of Alice's data
    curl -X POST http://127.0.0.1:8000/agent/memory.recall \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: bob" \\
        -d '{"intent": "What do you remember about me?"}'

    # Alice triggers GDPR Article 17 — forget everything
    curl -X POST http://127.0.0.1:8000/agent/memory.forget \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: alice" \\
        -d '{"intent": "Forget everything about me"}'

    # Health check lists every endpoint
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from agenticapi import (
    AgenticApp,
    APIKeyHeader,
    AuthCredentials,
    Authenticator,
    AuthUser,
    MemoryKind,
    MemoryRecord,
    SqliteMemoryStore,
)

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# 1. Persistent memory store
# ---------------------------------------------------------------------------
#
# In production you would point ``path=`` at a file on a persistent
# volume (or swap in a Redis / Postgres implementation of the
# :class:`MemoryStore` protocol). The demo uses a file in the working
# directory so a process restart proves the data is durable.
#
# The environment variable ``AGENTICAPI_MEMORY_DB`` lets the e2e test
# point the store at an isolated tmp file so parallel test runs never
# race on the same sqlite database.

_DEFAULT_DB_PATH = "./agenticapi_memory_demo.sqlite"
_DB_PATH = os.environ.get("AGENTICAPI_MEMORY_DB", _DEFAULT_DB_PATH)

memory = SqliteMemoryStore(path=_DB_PATH)


# ---------------------------------------------------------------------------
# 2. Authentication — needed to derive the memory scope
# ---------------------------------------------------------------------------
#
# Every memory record is written into ``scope="user:<id>"``. We deliberately
# require auth on every endpoint so the scope is always known at handler
# entry — there is no "anonymous" memory pool to leak into.

# A tiny "directory" of known users. In production this would be a
# database lookup or a JWT claim.
KNOWN_USERS: dict[str, dict[str, Any]] = {
    "alice": {"id": "alice", "display_name": "Alice"},
    "bob": {"id": "bob", "display_name": "Bob"},
    "carol": {"id": "carol", "display_name": "Carol"},
}


async def verify_user(credentials: AuthCredentials) -> AuthUser | None:
    """Map an ``X-User-Id`` header to a known user, or return None.

    AgenticAPI's ``Authenticator`` pipeline runs this before any
    dependency resolution, so handlers can rely on ``context.auth_user``
    being populated when we reach them.
    """
    user_id = credentials.credentials
    record = KNOWN_USERS.get(user_id)
    if record is None:
        return None
    return AuthUser(user_id=record["id"], username=record["display_name"], roles=("user",))


user_auth = Authenticator(
    scheme=APIKeyHeader(name="X-User-Id"),
    verify=verify_user,
)


# ---------------------------------------------------------------------------
# 3. Helper: convert an AuthUser into a memory scope string
# ---------------------------------------------------------------------------
#
# Handlers never hand-construct ``"user:alice"`` inline. They call
# ``_user_scope(context)`` which reads the ``auth_user`` the framework
# stashed in ``context.metadata`` and returns a well-formed scope.
# Centralising the scope-construction in one place is the pattern
# that makes C3 ``MemoryPolicy`` governance additive later — every
# read/write already flows through this helper, so a future policy
# hook only needs to wrap one function.


def _user_scope(context: AgentContext) -> str:
    """Return the canonical memory scope for the current request.

    Raises:
        RuntimeError: if the request reached the handler without an
            authenticated user. The Authenticator should have already
            rejected unauthenticated requests with a 401, so this is a
            safety net rather than a reachable branch in normal flow.
    """
    auth_user: AuthUser | None = context.metadata.get("auth_user")
    if auth_user is None:
        raise RuntimeError("memory endpoints require authentication")
    return f"user:{auth_user.user_id}"


# ---------------------------------------------------------------------------
# 4. Pydantic response models — typed, OpenAPI-visible, validated on return
# ---------------------------------------------------------------------------


class RememberedFact(BaseModel):
    """One fact the assistant just committed to semantic memory."""

    scope: str
    key: str
    value: Any
    kind: str
    tags: list[str]
    stored_at: datetime


class RecallResponse(BaseModel):
    """Everything we know about the current user."""

    scope: str
    facts: list[RememberedFact]
    total: int


class AskResponse(BaseModel):
    """Answer to a question, plus which memory kinds participated."""

    question: str
    answer: str
    response_cached: bool
    consulted_kinds: list[str]
    matched_key: str | None


class HistoryEntry(BaseModel):
    """One row of the conversation history (episodic memory)."""

    turn: int
    question: str
    answer: str
    at: datetime


class HistoryResponse(BaseModel):
    scope: str
    entries: list[HistoryEntry]


class ForgetResponse(BaseModel):
    scope: str
    removed: int
    message: str


# ---------------------------------------------------------------------------
# 5. The AgenticApp — memory is wired at construction time
# ---------------------------------------------------------------------------
#
# Passing ``memory=`` here makes the store available on every
# ``AgentContext`` the framework builds. Handlers read it via
# ``context.memory`` — they never import the store module directly.

app = AgenticApp(
    title="Persistent Memory Assistant",
    version="1.0.0",
    description=(
        "A memory-first personal assistant. Facts, conversation history, "
        "and cached answers all live in a persistent SqliteMemoryStore "
        "so the assistant never forgets. Each user is isolated in their "
        "own scope; GDPR forget ships as one call."
    ),
    memory=memory,
    auth=user_auth,  # every endpoint requires a known user
)


# ---------------------------------------------------------------------------
# 6. Helper: keyword extraction for the demo
# ---------------------------------------------------------------------------
#
# The assistant parses free-text intents with simple keyword matching so
# the example runs without an LLM key. A real deployment would swap this
# for an LLM backend; the memory choreography in the handlers is
# identical either way.

_CURRENCY_WORDS = {"currency", "money", "cash"}
_TIMEZONE_WORDS = {"timezone", "tz", "time zone"}
_DIET_WORDS = {"diet", "dietary", "vegetarian", "vegan", "allergy", "food"}
_NAME_WORDS = {"name", "who am i"}


def _classify_question(text: str) -> str | None:
    """Return the canonical memory key this question is asking about."""
    lower = text.lower()
    if any(w in lower for w in _CURRENCY_WORDS):
        return "currency"
    if any(w in lower for w in _TIMEZONE_WORDS):
        return "timezone"
    if any(w in lower for w in _DIET_WORDS):
        return "dietary"
    if any(w in lower for w in _NAME_WORDS):
        return "display_name"
    return None


def _extract_fact(text: str) -> tuple[str, Any] | None:
    """Pull a ``(key, value)`` pair out of a ``remember …`` intent.

    Recognises a short list of patterns so the curl walkthrough works
    out of the box. A real deployment would replace this with an LLM
    call that returns a validated Pydantic payload.
    """
    lower = text.lower()
    if "currency" in lower:
        # "currency is EUR" / "currency EUR"
        tokens = text.replace(",", " ").split()
        for i, token in enumerate(tokens):
            if token.lower() == "currency" and i + 2 < len(tokens) and tokens[i + 1].lower() == "is":
                return "currency", tokens[i + 2].strip(".").upper()
            if token.lower() == "currency" and i + 1 < len(tokens):
                candidate = tokens[i + 1].strip(".").upper()
                if candidate.isalpha() and len(candidate) == 3:
                    return "currency", candidate
    if "timezone" in lower or "time zone" in lower:
        tokens = text.split()
        for i, token in enumerate(tokens):
            if "/" in token and i > 0:
                return "timezone", token.strip(".,")
    if "vegetarian" in lower:
        return "dietary", "vegetarian"
    if "vegan" in lower:
        return "dietary", "vegan"
    return None


# ---------------------------------------------------------------------------
# 7. Endpoints
# ---------------------------------------------------------------------------


@app.agent_endpoint(
    name="memory.remember",
    description="Store a semantic fact about the current user.",
    response_model=RememberedFact,
)
async def remember(
    intent: Intent,
    context: AgentContext,
) -> RememberedFact:
    """Write one record into the user's semantic memory.

    Request body::

        {"intent": "Remember that my currency is EUR"}

    The handler extracts a ``(key, value)`` pair from the free-text
    intent and writes one :class:`MemoryRecord` under
    ``kind=semantic``. A real deployment would swap
    :func:`_extract_fact` for an LLM call that returns a validated
    Pydantic payload; the memory choreography is unchanged.

    Recognised facts (keyword-parsed by :func:`_extract_fact`):

    * ``currency`` — any three-letter ISO code following the word
      ``currency``
    * ``timezone`` — any IANA-shaped token (``Area/City``) following
      the word ``timezone``
    * ``dietary`` — the words ``vegetarian`` or ``vegan``
    """
    assert context.memory is not None, "memory must be configured"
    scope = _user_scope(context)

    extracted = _extract_fact(intent.raw)
    if extracted is None:
        raise ValueError(
            "could not infer a (key, value) pair from the intent — "
            "try 'Remember my currency is EUR', "
            "'Remember my timezone is Europe/Berlin', "
            "or 'Remember that I am vegetarian'",
        )
    key, value = extracted

    # Tag semantically meaningful rows so downstream queries can filter
    # on ``tag=preference`` / ``tag=dietary`` without scanning every
    # record.
    tags = ["preference"]
    if key == "dietary":
        tags.append("dietary")

    record = MemoryRecord(
        scope=scope,
        key=key,
        value=value,
        kind=MemoryKind.SEMANTIC,
        tags=tags,
    )
    await context.memory.put(record)

    return RememberedFact(
        scope=record.scope,
        key=record.key,
        value=record.value,
        kind=record.kind.value,
        tags=record.tags,
        stored_at=record.updated_at,
    )


@app.agent_endpoint(
    name="memory.recall",
    description="List everything the assistant remembers about the current user.",
    response_model=RecallResponse,
)
async def recall(
    intent: Intent,
    context: AgentContext,
) -> RecallResponse:
    """Return every semantic fact in the user's scope.

    Proves that one user's data is invisible to another user — call
    this endpoint as Bob after writing facts as Alice and observe
    that Bob sees an empty list.
    """
    assert context.memory is not None
    scope = _user_scope(context)
    records = await context.memory.search(scope=scope, kind=MemoryKind.SEMANTIC)
    facts = [
        RememberedFact(
            scope=r.scope,
            key=r.key,
            value=r.value,
            kind=r.kind.value,
            tags=r.tags,
            stored_at=r.updated_at,
        )
        for r in records
    ]
    return RecallResponse(scope=scope, facts=facts, total=len(facts))


@app.agent_endpoint(
    name="memory.ask",
    description="Answer a question using stored facts. Exercises all three memory kinds.",
    response_model=AskResponse,
)
async def ask(
    intent: Intent,
    context: AgentContext,
) -> AskResponse:
    """Answer a question from memory. Writes episodic + procedural records.

    Flow::

        1. Classify the question → canonical key.
        2. Check the **procedural** cache (``key=f"recipe:{q_key}"``).
           If it's a hit, serve the answer from there and flip
           ``response_cached=True``.
        3. Otherwise read the **semantic** record and build the answer.
           On the first successful answer, write the procedural
           recipe so the next identical question skips the lookup.
        4. Always append the turn to **episodic** memory (the
           conversation history).
    """
    assert context.memory is not None
    scope = _user_scope(context)

    question = intent.raw
    consulted: list[str] = []
    q_key = _classify_question(question)

    answer: str
    cached = False
    matched_key: str | None = None

    if q_key is None:
        answer = (
            "I am not sure what you are asking. Try 'What is my currency?', "
            "'What is my timezone?', 'What is my dietary preference?', "
            "or 'What is my name?'."
        )
    else:
        # Step 2: procedural lookup (the recipe cache)
        consulted.append(MemoryKind.PROCEDURAL.value)
        recipe = await context.memory.get(scope=scope, key=f"recipe:{q_key}")
        if recipe is not None:
            cached = True
            matched_key = q_key
            answer = str(recipe.value)
        else:
            # Step 3: fall back to the semantic fact
            consulted.append(MemoryKind.SEMANTIC.value)
            fact = await context.memory.get(scope=scope, key=q_key)
            if fact is None:
                answer = f"I don't know your {q_key} yet. Tell me with `memory.remember`."
            else:
                matched_key = q_key
                answer = f"Your {q_key} is {fact.value}."
                # Write the procedural recipe so the next call is a cache hit.
                await context.memory.put(
                    MemoryRecord(
                        scope=scope,
                        key=f"recipe:{q_key}",
                        value=answer,
                        kind=MemoryKind.PROCEDURAL,
                        tags=["recipe", q_key],
                    ),
                )

    # Step 4: episodic turn, regardless of how we reached the answer
    consulted.append(MemoryKind.EPISODIC.value)
    existing_turns = await context.memory.search(
        scope=scope,
        kind=MemoryKind.EPISODIC,
        key_prefix="turn:",
    )
    turn_number = len(existing_turns) + 1
    await context.memory.put(
        MemoryRecord(
            scope=scope,
            key=f"turn:{turn_number:06d}",
            value={
                "turn": turn_number,
                "question": question,
                "answer": answer,
                "at": datetime.now(tz=UTC).isoformat(),
            },
            kind=MemoryKind.EPISODIC,
            tags=["history"],
        ),
    )

    return AskResponse(
        question=question,
        answer=answer,
        response_cached=cached,
        consulted_kinds=consulted,
        matched_key=matched_key,
    )


@app.agent_endpoint(
    name="memory.history",
    description="Replay the user's conversation history from episodic memory.",
    response_model=HistoryResponse,
)
async def history(
    intent: Intent,
    context: AgentContext,
) -> HistoryResponse:
    """Return the most recent episodic records in chronological order."""
    assert context.memory is not None
    scope = _user_scope(context)
    rows = await context.memory.search(
        scope=scope,
        kind=MemoryKind.EPISODIC,
        key_prefix="turn:",
        limit=50,
    )
    # ``search`` returns newest-first. Flip to chronological for display.
    rows_sorted = sorted(rows, key=lambda r: r.key)
    entries = [
        HistoryEntry(
            turn=int(r.value["turn"]),
            question=str(r.value["question"]),
            answer=str(r.value["answer"]),
            at=datetime.fromisoformat(str(r.value["at"])),
        )
        for r in rows_sorted
    ]
    return HistoryResponse(scope=scope, entries=entries)


@app.agent_endpoint(
    name="memory.forget",
    description="GDPR Article 17 — drop every record in the user's scope.",
    response_model=ForgetResponse,
)
async def forget(
    intent: Intent,
    context: AgentContext,
) -> ForgetResponse:
    """Hard-delete every record under the current user's scope.

    This is the "right to be forgotten" primitive. After this call,
    ``memory.recall`` returns an empty list for the same user, and
    subsequent ``memory.ask`` calls see no procedural cache hits.
    """
    assert context.memory is not None
    scope = _user_scope(context)
    removed = await context.memory.forget(scope=scope)
    return ForgetResponse(
        scope=scope,
        removed=removed,
        message=(
            f"Removed {removed} record(s). Every fact, history entry, "
            "and cached recipe under this scope has been deleted."
        ),
    )


# ---------------------------------------------------------------------------
# 8. Convenience: export the paths the e2e test resets between runs
# ---------------------------------------------------------------------------

__all__ = ["_DB_PATH", "app", "memory"]
