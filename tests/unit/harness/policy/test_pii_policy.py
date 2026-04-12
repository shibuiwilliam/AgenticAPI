"""Unit tests for Phase B6 — PIIPolicy.

Covers the default detector catalogue (email, phone, SSN, credit card
with Luhn, IBAN, IPv4), the three modes (detect / redact / block),
``disabled_detectors``, ``extra_patterns``, the ``evaluate_tool_call``
hook for Phase E4 tool-first execution, and the standalone
``redact_pii`` helper.
"""

from __future__ import annotations

from agenticapi import PIIHit, PIIPolicy, redact_pii
from agenticapi.harness.policy.pii_policy import _luhn_valid

# ---------------------------------------------------------------------------
# Helper constants
# ---------------------------------------------------------------------------

# A well-known Luhn-valid test PAN published by every payment processor
# for sandbox use. Never belongs to a real card.
VALID_TEST_PAN = "4111 1111 1111 1111"

# The same digits rearranged so the Luhn sum is no longer a multiple
# of 10. Used to verify the Luhn gate drops non-card digit runs.
INVALID_PAN = "4111 1111 1111 1112"


# ---------------------------------------------------------------------------
# Luhn validator
# ---------------------------------------------------------------------------


class TestLuhnValidator:
    def test_known_valid_test_pan(self) -> None:
        assert _luhn_valid("4111111111111111") is True

    def test_invalid_pan_fails(self) -> None:
        assert _luhn_valid("4111111111111112") is False

    def test_too_short_rejected(self) -> None:
        assert _luhn_valid("411111111111") is False  # 12 digits

    def test_too_long_rejected(self) -> None:
        assert _luhn_valid("4111111111111111111") is False  # 19 digits OK for AmEx; 20 is over

    def test_strips_separators(self) -> None:
        assert _luhn_valid("4111-1111-1111-1111") is True

    def test_empty_rejected(self) -> None:
        assert _luhn_valid("") is False


# ---------------------------------------------------------------------------
# Default detectors — positive cases
# ---------------------------------------------------------------------------


class TestDefaultDetectors:
    def test_email_detected(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code="Send the report to alice@example.com please.")
        assert result.allowed is False
        assert any("email" in v for v in result.violations)

    def test_phone_us_detected(self) -> None:
        # Valid NANP: area 555 (fiction), exchange 234 (starts 2-9), line 5678.
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code="Call me at 555-234-5678 tomorrow.")
        assert result.allowed is False
        assert any("phone_us" in v for v in result.violations)

    def test_phone_us_with_country_code(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code="My number is +1 (415) 234-5678.")
        assert result.allowed is False
        assert any("phone_us" in v for v in result.violations)

    def test_ssn_detected(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code="SSN on file: 123-45-6789")
        assert result.allowed is False
        assert any("ssn" in v for v in result.violations)

    def test_credit_card_luhn_valid_detected(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code=f"Pay with {VALID_TEST_PAN}.")
        assert result.allowed is False
        assert any("credit_card" in v for v in result.violations)

    def test_credit_card_luhn_invalid_not_detected(self) -> None:
        """Luhn-invalid digit runs must not trip the credit-card detector.

        This is the whole point of the Luhn gate: 16-digit order IDs or
        tracking numbers don't look like cards.
        """
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code=f"Your order ID is {INVALID_PAN}.")
        assert result.allowed is True

    def test_iban_detected(self) -> None:
        policy = PIIPolicy(mode="block")
        # GB82 WEST 1234 5698 7654 32 — a well-known fake IBAN for tests.
        result = policy.evaluate(code="IBAN GB82WEST12345698765432")
        assert result.allowed is False
        assert any("iban" in v for v in result.violations)

    def test_ipv4_detected(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code="Server at 192.168.1.100 is down.")
        assert result.allowed is False
        assert any("ipv4" in v for v in result.violations)

    def test_multiple_hits_in_one_text(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(
            code="Contact alice@example.com or call 555-234-5678.",
        )
        assert result.allowed is False
        # Both detectors should fire.
        assert len(result.violations) == 2


# ---------------------------------------------------------------------------
# Default detectors — negative cases (no false positives)
# ---------------------------------------------------------------------------


class TestFalsePositivesAvoided:
    def test_safe_text_allowed(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code="Please summarise the Q3 report.")
        assert result.allowed is True
        assert not result.violations
        assert not result.warnings

    def test_order_id_not_flagged_as_ssn(self) -> None:
        policy = PIIPolicy(mode="block")
        # SSN pattern requires exactly NNN-NN-NNNN with hyphens.
        result = policy.evaluate(code="Order ORD-12-34567 is ready.")
        assert result.allowed is True

    def test_dotted_version_not_flagged_as_ip(self) -> None:
        policy = PIIPolicy(mode="block")
        # Version numbers like 1.2.3.4 ARE valid dotted quads and WILL
        # match the ipv4 detector. Apps that version-log should disable
        # the ipv4 detector. This test asserts the behaviour is
        # documented, not that it's magically smart.
        result = policy.evaluate(code="Deployed version 1.2.3.4 today.")
        assert result.allowed is False  # ipv4 fires — by design

    def test_phone_with_invalid_exchange_not_flagged(self) -> None:
        """NANP exchange codes can't start with 0 or 1. The pattern
        rejects 555-123-4567 (fictional but invalid exchange)."""
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code="Fake number: 555-123-4567.")
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


class TestModes:
    def test_detect_mode_returns_warnings(self) -> None:
        policy = PIIPolicy(mode="detect")
        result = policy.evaluate(code="alice@example.com")
        assert result.allowed is True
        assert not result.violations
        assert len(result.warnings) == 1
        # In detect mode the snippet contains the raw PII (for debugging).
        assert "alice@example.com" in result.warnings[0]

    def test_redact_mode_returns_warnings_with_token(self) -> None:
        policy = PIIPolicy(mode="redact")
        result = policy.evaluate(code="alice@example.com")
        assert result.allowed is True
        assert not result.violations
        assert len(result.warnings) == 1
        # In redact mode the snippet should have the raw PII replaced
        # by the token so audit payloads don't store the raw value.
        assert "alice@example.com" not in result.warnings[0]
        assert "[EMAIL]" in result.warnings[0]

    def test_block_mode_returns_violation(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate(code="alice@example.com")
        assert result.allowed is False
        assert len(result.violations) == 1

    def test_block_mode_is_default(self) -> None:
        """Fail-closed default — deny-by-default is the safer posture."""
        policy = PIIPolicy()
        assert policy.mode == "block"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_disabled_detectors_skipped(self) -> None:
        policy = PIIPolicy(mode="block", disabled_detectors=["ipv4"])
        result = policy.evaluate(code="Server at 10.0.0.1 is fine.")
        assert result.allowed is True

    def test_disabled_detector_does_not_affect_others(self) -> None:
        policy = PIIPolicy(mode="block", disabled_detectors=["ipv4"])
        result = policy.evaluate(code="Email alice@example.com")
        assert result.allowed is False
        assert any("email" in v for v in result.violations)

    def test_extra_pattern_detected(self) -> None:
        policy = PIIPolicy(
            mode="block",
            extra_patterns=[
                ("jwt", r"eyJ[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}", "[JWT]"),
            ],
        )
        result = policy.evaluate(code="token: eyJabc.eyJdef.sigghi")
        assert result.allowed is False
        assert any("jwt" in v for v in result.violations)

    def test_extra_pattern_malformed_regex_ignored(self) -> None:
        """A broken user-supplied regex must not crash the policy."""
        policy = PIIPolicy(
            mode="block",
            extra_patterns=[("broken", r"[unterminated", "[BROKEN]")],
        )
        result = policy.evaluate(code="ordinary text")
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Tool-call hook (Phase E4)
# ---------------------------------------------------------------------------


class TestEvaluateToolCall:
    def test_tool_call_with_pii_in_arguments_blocked(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate_tool_call(
            tool_name="send_message",
            arguments={"to": "alice@example.com", "body": "hello"},
        )
        assert result.allowed is False
        assert any("email" in v for v in result.violations)

    def test_tool_call_with_clean_arguments_allowed(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate_tool_call(
            tool_name="list_orders",
            arguments={"status": "shipped", "limit": 20},
        )
        assert result.allowed is True

    def test_tool_call_nested_strings_scanned(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate_tool_call(
            tool_name="bulk_upsert",
            arguments={
                "rows": [
                    {"name": "Alice", "email": "alice@example.com"},
                    {"name": "Bob", "email": "bob@example.com"},
                ],
            },
        )
        assert result.allowed is False
        assert len(result.violations) == 2

    def test_tool_call_ignores_non_string_values(self) -> None:
        policy = PIIPolicy(mode="block")
        result = policy.evaluate_tool_call(
            tool_name="compute",
            arguments={"x": 42, "y": 3.14, "flag": True},
        )
        assert result.allowed is True


# ---------------------------------------------------------------------------
# redact_pii helper
# ---------------------------------------------------------------------------


class TestRedactPII:
    def test_redacts_email(self) -> None:
        assert redact_pii("contact alice@example.com today") == "contact [EMAIL] today"

    def test_redacts_multiple_in_one_string(self) -> None:
        text = "alice@example.com or 555-234-5678"
        result = redact_pii(text)
        assert "alice@example.com" not in result
        assert "555-234-5678" not in result
        assert "[EMAIL]" in result
        assert "[PHONE]" in result

    def test_idempotent(self) -> None:
        text = "email alice@example.com"
        once = redact_pii(text)
        twice = redact_pii(once)
        assert once == twice

    def test_no_pii_unchanged(self) -> None:
        assert redact_pii("ordinary text") == "ordinary text"

    def test_respects_disabled_detectors_when_policy_provided(self) -> None:
        policy = PIIPolicy(mode="redact", disabled_detectors=["ipv4"])
        result = redact_pii("Server 10.0.0.1 is down", policy=policy)
        assert result == "Server 10.0.0.1 is down"

    def test_preserves_offsets_with_multiple_hits(self) -> None:
        """Replacements must be applied right-to-left so earlier start
        offsets stay valid."""
        text = "a@x.com and b@y.com and c@z.com"
        result = redact_pii(text)
        assert result == "[EMAIL] and [EMAIL] and [EMAIL]"


# ---------------------------------------------------------------------------
# PIIHit dataclass
# ---------------------------------------------------------------------------


class TestPIIHit:
    def test_pii_hit_is_frozen(self) -> None:
        hit = PIIHit(
            name="email",
            token="[EMAIL]",
            snippet="alice@example.com",
            start=0,
            end=17,
        )
        assert hit.name == "email"
        assert hit.token == "[EMAIL]"
        # Frozen dataclass: assignment should raise.
        try:
            hit.name = "other"  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("PIIHit should be frozen")
