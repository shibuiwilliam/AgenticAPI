"""Approved-code cache (Phase C5).

Why an approved-code cache matters.

    Every request through :meth:`AgenticApp._execute_with_harness`
    pays for a fresh code-generation call to the LLM. In practice
    most production agents see the *same* intent shapes hundreds of
    times per hour — "list orders from last week", "summarise ticket
    123", "count rows where status = 'open'". Each repetition burns
    $0.005 to $0.05 and adds 300 to 900 ms of latency for a code block the
    harness already generated, approved, and shipped yesterday.

    The approved-code cache is the trivial fix: key a lookup on the
    *deterministic inputs* to the code-gen prompt, and on a hit, skip
    the LLM call entirely. Cached code still runs through every
    downstream layer — :class:`PolicyEvaluator`, static AST analysis,
    the approval workflow, the sandbox, monitors, validators — so the
    cache is **strictly an LLM-call optimisation**, never a safety
    downgrade.

What makes a cache key.

    The key is a SHA-256 hash of a tuple of deterministic inputs:

    * ``endpoint_name`` — different endpoints may have different
      prompts / policies and must not share cache entries.
    * ``intent_action`` / ``intent_domain`` — the classification
      that drove the original code-gen decision.
    * ``tool_set`` — the sorted names of every registered tool.
      Adding or removing a tool invalidates the cache for that
      endpoint because the prompt changes.
    * ``policy_set`` — the sorted policy class names. Swapping
      policies could change what the LLM is allowed to emit, so we
      invalidate on policy composition changes too.
    * A normalised form of the intent parameters (sorted JSON).
      The same intent asked with different parameters is a
      different cache entry.

    The key intentionally does **not** include the raw user text,
    because different paraphrases ("list last week's orders", "show
    orders from the past week") should reuse the same approved code.
    Callers that want stricter keying can include parameters that
    distinguish paraphrases.

Staleness and invalidation.

    * Each entry carries a ``created_at`` timestamp. Callers can
      configure a TTL on the cache; entries older than the TTL are
      treated as misses.
    * There's no active background eviction — the bound is the
      cache's ``max_entries`` parameter with a simple LRU-by-
      insertion-order policy.
    * Policy / tool changes invalidate automatically because they
      change the cache key.
    * ``clear()`` wipes the whole cache, useful for rollouts.

Out of scope for C5.

    * Multi-host shared cache (Redis backend) — same substitution
      pattern as F7's :class:`StreamStore`.
    * Per-intent semantic matching (embedding keys) — that's C2's
      job.
    * Background revalidation / preemptive regeneration — C7 will
      land a replay-based cache audit.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class CachedCode:
    """A single approved-code cache entry.

    Attributes:
        key: The deterministic cache key used to look this up.
        code: The generated Python source code.
        reasoning: Optional LLM reasoning — replayed into the audit
            trace so the historical context is preserved.
        confidence: The confidence score the LLM originally reported.
        created_at: UTC timestamp of when the entry was cached.
        hits: Running count of how many times this entry has been
            served. Bumped in-place on every lookup; useful for
            diagnostics (``print(cache.top_entries())``).
    """

    key: str
    code: str
    reasoning: str | None
    confidence: float
    created_at: datetime
    hits: int = 0


@runtime_checkable
class CodeCache(Protocol):
    """Protocol every approved-code cache backend satisfies.

    The default implementation :class:`InMemoryCodeCache` is
    single-process and unbounded-except-for-``max_entries``; a
    Redis-backed implementation can drop in without touching
    callers.
    """

    def get(self, key: str) -> CachedCode | None:
        """Look up a cached entry. Returns ``None`` on miss."""
        ...

    def put(self, entry: CachedCode) -> None:
        """Store an entry. Overwrites an existing entry with the same key."""
        ...

    def clear(self) -> None:
        """Drop every entry. Used on rollouts or test setup."""
        ...


def make_cache_key(
    *,
    endpoint_name: str,
    intent_action: str,
    intent_domain: str,
    tool_names: Iterable[str],
    policy_names: Iterable[str],
    intent_parameters: dict[str, Any] | None = None,
) -> str:
    """Build a deterministic SHA-256 cache key.

    The key factors everything that could change what the LLM
    would generate for a given intent:

    * Endpoint (different prompts per endpoint).
    * Intent action and domain (the classification the prompt
      conditions on).
    * The **sorted** set of tool names (adding a tool changes the
      prompt's tool catalogue).
    * The **sorted** set of policy class names (swapping policies
      could change what the LLM is allowed to emit).
    * Normalised intent parameters.

    Returns a hex-encoded SHA-256 digest so callers can use it as
    both a dict key and a log field without further processing.
    """
    payload = {
        "endpoint": endpoint_name,
        "action": intent_action,
        "domain": intent_domain,
        "tools": sorted(set(tool_names)),
        "policies": sorted(set(policy_names)),
        "params": _normalise_parameters(intent_parameters or {}),
    }
    # ``sort_keys=True`` guarantees dict ordering is stable regardless
    # of insertion order so two semantically-identical requests
    # produce the same hash.
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalise_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-sorted copy of ``parameters`` for stable hashing.

    Dictionaries and lists are recursively normalised so that
    ``{"a": [2, 1]}`` and ``{"a": [1, 2]}`` hash differently (order
    matters) but ``{"b": 1, "a": 2}`` and ``{"a": 2, "b": 1}``
    produce the same canonical form.
    """
    out: dict[str, Any] = {}
    for k in sorted(parameters.keys()):
        v = parameters[k]
        if isinstance(v, dict):
            out[k] = _normalise_parameters(v)
        else:
            out[k] = v
    return out


class InMemoryCodeCache:
    """Bounded LRU-by-insertion :class:`CodeCache` implementation.

    Entries are stored in an :class:`OrderedDict` so the oldest
    insertion can be evicted in O(1) when ``max_entries`` is
    reached. The cache is intentionally single-process; multi-host
    deployments should swap in a Redis-backed implementation
    behind the :class:`CodeCache` protocol.

    Example:
        cache = InMemoryCodeCache(max_entries=500, ttl_seconds=3600)
        entry = cache.get(key)
        if entry is None:
            code = await generate_code(...)
            cache.put(CachedCode(key=key, code=code, ...))
    """

    def __init__(
        self,
        *,
        max_entries: int = 1000,
        ttl_seconds: float | None = None,
    ) -> None:
        """Initialize the cache.

        Args:
            max_entries: Hard cap on the number of stored entries.
                When exceeded, the oldest insertion is evicted.
                Defaults to 1000, which is enough headroom for most
                production agents without unbounded memory growth.
            ttl_seconds: Optional time-to-live for entries. When
                set, lookups that return a stale entry report a
                miss (and the stale entry is evicted). ``None``
                disables TTL — entries live until the cache fills
                up or :meth:`clear` is called.
        """
        self._entries: OrderedDict[str, CachedCode] = OrderedDict()
        self._max_entries = max(1, int(max_entries))
        self._ttl_seconds = ttl_seconds

    def get(self, key: str) -> CachedCode | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._ttl_seconds is not None:
            age = (datetime.now(tz=UTC) - entry.created_at).total_seconds()
            if age > self._ttl_seconds:
                # Stale — treat as miss and evict.
                self._entries.pop(key, None)
                logger.debug("code_cache_entry_expired", key=key[:16], age_seconds=age)
                return None
        # Bump hit counter. ``CachedCode`` is frozen, so we replace
        # the entry with an updated copy — cheap because the fields
        # are immutable primitives.
        bumped = CachedCode(
            key=entry.key,
            code=entry.code,
            reasoning=entry.reasoning,
            confidence=entry.confidence,
            created_at=entry.created_at,
            hits=entry.hits + 1,
        )
        self._entries[key] = bumped
        # Move to the "recent" end of the LRU.
        self._entries.move_to_end(key)
        return bumped

    def put(self, entry: CachedCode) -> None:
        # Overwrite or insert.
        self._entries[entry.key] = entry
        self._entries.move_to_end(entry.key)
        # Evict oldest until we're at or under the cap.
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    # Diagnostics -------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def top_entries(self, limit: int = 5) -> list[CachedCode]:
        """Return the ``limit`` most-hit entries. Debug helper."""
        return sorted(self._entries.values(), key=lambda e: e.hits, reverse=True)[:limit]


__all__ = [
    "CachedCode",
    "CodeCache",
    "InMemoryCodeCache",
    "make_cache_key",
]
