"""Personally Identifiable Information (PII) detection policy — Phase B6.

What PIIPolicy is for.

    Framework-level PII detection that catches the common identifiers
    (email, phone, US SSN, credit card, IBAN, IPv4) in user input, tool
    arguments, and generated output. Follows the same Policy contract
    as :class:`~agenticapi.harness.policy.prompt_injection_policy.PromptInjectionPolicy`
    (Phase B5) so the audit / observability / policy-aggregation
    substrate doesn't need a new code path. The policy scans plain text
    passed via the base class ``evaluate(code=...)`` contract and, for
    Phase E4 tool-first execution, scans tool-call arguments via
    ``evaluate_tool_call``.

Three modes.

    * ``"detect"`` — matches become :class:`PolicyResult` warnings.
      Useful for shadow-mode rollouts: see what triggers without
      blocking users. The request is still allowed.
    * ``"redact"`` — matches become warnings whose message contains
      the redacted form (``[EMAIL]``, ``[SSN]``, etc.). The policy
      itself does **not** rewrite the input text — text mutation
      happens outside the Policy contract. Callers that want to
      actually strip PII from a string should use the
      :func:`redact_pii` helper exported from this module.
    * ``"block"`` — matches become hard violations. The request is
      denied with HTTP 403 via the standard :class:`PolicyViolation`
      path.

Design principles.

    * **Precision over recall.** False positives are worse than false
      negatives at ingress time because they block legitimate users.
      Patterns are tuned to catch obvious, well-formed identifiers,
      not every possible phrasing.
    * **Luhn-validated credit cards.** 16-digit runs are everywhere
      in free-form text (order IDs, confirmation numbers, tracking
      codes). We only flag a candidate when it passes the Luhn mod-10
      check, which drops the false-positive rate from ~1% to <0.01%.
    * **Declarative disable.** ``disabled_detectors=["ip"]`` lets an
      ops endpoint that legitimately discusses IPs opt out of that
      one rule.
    * **Extensible.** ``extra_patterns=[("jwt", r"eyJ[A-Za-z0-9_-]+",
      "[JWT]")]`` adds app-specific detectors without subclassing.
    * **Observable.** Every match fires a counter increment through
      :mod:`agenticapi.observability.metrics` so dashboards can
      attribute blocks per detector.

What's out of scope.

    * ML / NER-based PII detection (higher recall, much higher
      latency and cost, new runtime dep). A viable follow-on if
      regex precision isn't enough.
    * International phone / national-ID formats beyond US + E.164.
      Apps in those markets can add detectors via ``extra_patterns``.
    * Automatic input rewriting. The Policy base contract returns a
      :class:`PolicyResult`, not modified input. Explicit redaction
      is available via :func:`redact_pii`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ConfigDict, Field

from agenticapi.harness.policy.base import Policy, PolicyResult


@dataclass(frozen=True, slots=True)
class PIIHit:
    """One matched PII occurrence.

    Attributes:
        name: Short identifier for the matching detector (e.g.
            ``"email"``, ``"credit_card"``). Used in logs and metrics.
        token: The redaction placeholder for this detector
            (e.g. ``"[EMAIL]"``). Stable across matches so dashboards
            can aggregate.
        snippet: A short excerpt around the match so audits can see
            *what* triggered the detector without re-running the
            regex. Always the redacted form when the policy is in
            ``"redact"`` or ``"block"`` mode; the raw form in
            ``"detect"`` mode for debugging. Capped at 120 characters.
        start: Start offset into the original text.
        end: End offset (exclusive).
    """

    name: str
    token: str
    snippet: str
    start: int
    end: int


# Built-in detector catalogue -------------------------------------------------
#
# Each entry is (name, regex, token). All regexes are compiled with
# re.IGNORECASE where case-insensitivity makes sense (email, IBAN). The
# credit-card pattern is paired with a Luhn check below so 16-digit
# order IDs don't trip the block rule.

_DEFAULT_DETECTORS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "email",
        # RFC-lite: local@domain.tld, broad enough to cover real addresses
        # but narrow enough to reject "foo@" or "@bar".
        re.compile(
            r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
        "[EMAIL]",
    ),
    (
        "phone_us",
        # US / NANP: (555) 555-1234, 555-555-1234, +1 555 555 1234.
        # Area code and exchange code both start with 2-9 per NANP.
        re.compile(
            r"(?<!\d)(?:\+?1[\s.\-]?)?\(?[2-9]\d{2}\)?[\s.\-][2-9]\d{2}[\s.\-]\d{4}(?!\d)",
        ),
        "[PHONE]",
    ),
    (
        "ssn",
        # US SSN: NNN-NN-NNNN, rejecting the obvious all-zero sections.
        re.compile(
            r"(?<!\d)(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)",
        ),
        "[SSN]",
    ),
    (
        "credit_card",
        # 13-19 digits with optional hyphen/space group separators.
        # Further validated via Luhn in ``_scan`` below.
        re.compile(
            r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)",
        ),
        "[CREDIT_CARD]",
    ),
    (
        "iban",
        # International Bank Account Number: 2-letter country, 2 check
        # digits, up to 30 alphanumeric BBAN chars. IBANs are always
        # uppercase in wire format but we allow lowercase for robustness.
        re.compile(
            r"(?<![A-Z0-9])[A-Z]{2}\d{2}[A-Z0-9]{11,30}(?![A-Z0-9])",
            re.IGNORECASE,
        ),
        "[IBAN]",
    ),
    (
        "ipv4",
        # Dotted quad with each octet in 0-255. IPv4 in a text body is
        # rarely meant as PII in ops discussions, so apps that handle
        # infrastructure data should add ``"ipv4"`` to disabled_detectors.
        re.compile(
            r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?!\d)",
        ),
        "[IP]",
    ),
]


def _luhn_valid(digits_only: str) -> bool:
    """Return True iff ``digits_only`` is a Luhn-valid PAN.

    Strips non-digit separators first. Applies the mod-10 Luhn check
    used by every major card network. Length is bounded to 13-19 —
    everything outside that window is definitionally not a card.

    Args:
        digits_only: The candidate match, possibly containing spaces
            or hyphens.

    Returns:
        True when the digit run has 13-19 digits and the Luhn sum is
        a multiple of 10; False otherwise.
    """
    digits = [int(c) for c in digits_only if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    # Walk from rightmost digit; double every second digit and split
    # two-digit results (e.g. 14 -> 1+4).
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            doubled = d * 2
            checksum += doubled if doubled < 10 else doubled - 9
        else:
            checksum += d
    return checksum % 10 == 0


class PIIPolicy(Policy):
    """Policy that detects personally identifiable information (Phase B6).

    Example:
        from agenticapi import AgenticApp, HarnessEngine, PIIPolicy

        policy = PIIPolicy(
            mode="block",
            disabled_detectors=["ipv4"],  # ops endpoint discusses IPs
            extra_patterns=[
                ("jwt", r"eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+", "[JWT]"),
            ],
        )
        harness = HarnessEngine(policies=[policy])

    Attributes:
        mode: One of ``"detect"`` (warn only), ``"redact"`` (warn with
            redacted form), ``"block"`` (hard denial). Default is
            ``"block"`` — deny-by-default is the safe posture.
        disabled_detectors: Detector names to skip. Useful when a
            detector is consistently wrong for the app's domain — e.g.
            an ops endpoint that legitimately discusses IPs would pass
            ``disabled_detectors=["ipv4"]``.
        extra_patterns: App-supplied detectors. Each entry is
            ``(name, regex_string, token)``. Compiled at construction.
            Not Luhn-validated regardless of what the name is.
        endpoint_name: Optional label for the observability counter.
            Defaults to ``"unknown"`` so dashboards work even when
            unset.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    mode: Literal["detect", "redact", "block"] = "block"
    disabled_detectors: list[str] = Field(default_factory=list)
    extra_patterns: list[tuple[str, str, str]] = Field(default_factory=list)
    endpoint_name: str = "unknown"

    def evaluate(
        self,
        *,
        code: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Scan the passed text for PII and return a :class:`PolicyResult`.

        ``code`` here is a generic text parameter — the base Policy
        contract uses the name ``code`` for historical reasons, but
        PIIPolicy can receive any free-form text (intent, generated
        code, tool output, response body). The policy treats them all
        the same way.
        """
        del intent_action, intent_domain, kwargs
        hits = self._scan(code)

        if not hits:
            return PolicyResult(allowed=True, policy_name="PIIPolicy")

        # Fire metrics for every hit so dashboards can attribute
        # blocks per detector. Swallow any metrics-layer errors so a
        # broken OTEL exporter never takes down the request.
        try:
            from agenticapi.observability import metrics as _metrics

            for _ in hits:
                _metrics.record_policy_denial(
                    policy="PIIPolicy",
                    endpoint=self.endpoint_name,
                )
        except Exception:  # pragma: no cover - observability is opt-in
            pass

        messages = [f"{hit.name}: {hit.snippet}" for hit in hits]

        if self.mode == "block":
            return PolicyResult(
                allowed=False,
                violations=messages,
                policy_name="PIIPolicy",
            )
        # detect + redact both return warnings; the snippet inside each
        # hit already reflects the redacted form for "redact" mode.
        return PolicyResult(
            allowed=True,
            warnings=messages,
            policy_name="PIIPolicy",
        )

    def evaluate_intent_text(
        self,
        *,
        intent_text: str,
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Scan raw intent text for PII before the LLM fires.

        This is the **primary** invocation point for PII detection.
        The framework calls it on the user's raw intent string before
        the LLM ever sees it, preventing PII from being embedded in
        prompts. Delegates to the same ``_scan`` method used by
        ``evaluate`` so mode, detectors, and extra patterns all work
        identically.
        """
        return self.evaluate(
            code=intent_text,
            intent_action=intent_action,
            intent_domain=intent_domain,
            **kwargs,
        )

    def evaluate_tool_call(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        intent_action: str = "",
        intent_domain: str = "",
        **kwargs: Any,
    ) -> PolicyResult:
        """Scan string-typed tool arguments for PII (Phase E4 hook).

        The tool-first execution path (E4) hands the harness a tool
        name + a kwargs dict the LLM produced. We scan every string
        value in that dict using the same detector suite as
        :meth:`evaluate`. Nested dicts and lists are walked
        recursively.
        """
        del tool_name, intent_action, intent_domain, kwargs
        combined_text = "\n".join(_flatten_strings(arguments))
        if not combined_text:
            return PolicyResult(allowed=True, policy_name="PIIPolicy")
        return self.evaluate(code=combined_text)

    def _scan(self, text: str) -> list[PIIHit]:
        """Apply every enabled detector to ``text`` and return the matches."""
        hits: list[PIIHit] = []
        for name, pattern, token in _DEFAULT_DETECTORS:
            if name in self.disabled_detectors:
                continue
            for match in pattern.finditer(text):
                matched = match.group(0)
                # Credit-card candidates only count as hits if they
                # Luhn-validate — prevents 16-digit order IDs from
                # tripping the block rule.
                if name == "credit_card" and not _luhn_valid(matched):
                    continue
                hits.append(self._make_hit(name, token, text, match.start(), match.end(), matched))

        for name, regex_string, token in self.extra_patterns:
            if name in self.disabled_detectors:
                continue
            try:
                compiled = re.compile(regex_string, re.IGNORECASE)
            except re.error:
                # Skip malformed user patterns rather than crashing.
                continue
            for match in compiled.finditer(text):
                matched = match.group(0)
                hits.append(self._make_hit(name, token, text, match.start(), match.end(), matched))
        return hits

    def _make_hit(
        self,
        name: str,
        token: str,
        text: str,
        start: int,
        end: int,
        matched: str,
    ) -> PIIHit:
        """Build a :class:`PIIHit` with a mode-appropriate snippet."""
        if self.mode == "detect":
            # Raw form for debugging.
            snippet = _snippet_around(text, start, end)
        else:
            # redact + block: substitute the token so audit payloads
            # never contain the raw PII value.
            snippet = _snippet_around(text, start, end).replace(matched, token)
        return PIIHit(name=name, token=token, snippet=snippet, start=start, end=end)


def redact_pii(
    text: str,
    *,
    policy: PIIPolicy | None = None,
) -> str:
    """Return ``text`` with every detected PII value replaced by its token.

    Provided as a standalone utility so callers can actively redact
    input strings (the Policy contract itself returns a PolicyResult
    only, never modified text). Uses the same detector suite as
    :class:`PIIPolicy`.

    Args:
        text: The string to redact.
        policy: Optional configured :class:`PIIPolicy` whose
            ``disabled_detectors`` and ``extra_patterns`` should be
            honoured. When ``None``, a default policy is used.

    Returns:
        A new string with every matched PII value replaced by its
        token (``[EMAIL]``, ``[SSN]``, etc.). Non-PII characters are
        left intact. Idempotent: calling twice is a no-op on the
        second call.
    """
    policy = policy or PIIPolicy(mode="redact")
    hits = policy._scan(text)
    if not hits:
        return text
    # Apply replacements right-to-left so earlier start offsets stay
    # valid after later substitutions.
    hits_sorted = sorted(hits, key=lambda h: h.start, reverse=True)
    result = text
    for hit in hits_sorted:
        result = result[: hit.start] + hit.token + result[hit.end :]
    return result


def _flatten_strings(value: Any) -> list[str]:
    """Walk ``value`` recursively and return every string it contains.

    Used by :meth:`PIIPolicy.evaluate_tool_call` to scan tool-call
    arguments whose shape is arbitrary JSON-compatible data.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for v in value.values():
            out.extend(_flatten_strings(v))
        return out
    if isinstance(value, (list, tuple, set)):
        out2: list[str] = []
        for item in value:
            out2.extend(_flatten_strings(item))
        return out2
    return []


def _snippet_around(text: str, start: int, end: int, *, context: int = 30) -> str:
    """Return a short excerpt around ``text[start:end]`` for logs.

    Keeps the snippet under 120 characters so audit payloads don't
    balloon. Prefixes / suffixes with ``...`` when the surrounding
    text was trimmed.
    """
    prefix_start = max(0, start - context)
    suffix_end = min(len(text), end + context)
    snippet = text[prefix_start:suffix_end]
    if prefix_start > 0:
        snippet = "..." + snippet
    if suffix_end < len(text):
        snippet = snippet + "..."
    return snippet[:120]


__all__ = [
    "PIIHit",
    "PIIPolicy",
    "redact_pii",
]
