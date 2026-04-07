"""Intent model and parser for natural language requests.

Provides the Intent data class representing a parsed user intent,
IntentScope for declarative scope matching, and IntentParser for
converting raw natural language into structured Intent objects.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

from agenticapi.exceptions import IntentParseError
from agenticapi.runtime.prompts.intent_parsing import build_intent_parsing_prompt

if TYPE_CHECKING:
    from agenticapi.runtime.llm.base import LLMBackend

logger = structlog.get_logger(__name__)


class IntentAction(StrEnum):
    """Action type classification for intents."""

    READ = "read"
    WRITE = "write"
    ANALYZE = "analyze"
    EXECUTE = "execute"
    CLARIFY = "clarify"


@dataclass(frozen=True, slots=True)
class Intent:
    """Parsed intent representing a user's request.

    Immutable data class serving as the starting point for agent processing.

    Attributes:
        raw: The original natural language request.
        action: The classified action type.
        domain: The domain area (e.g., "order", "product", "user").
        parameters: Extracted parameters from the request.
        confidence: Parsing confidence score (0.0-1.0).
        ambiguities: List of detected ambiguities needing clarification.
        session_context: Accumulated session context from prior turns.
    """

    raw: str
    action: IntentAction
    domain: str
    parameters: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    ambiguities: list[str] = field(default_factory=list)
    session_context: dict[str, Any] = field(default_factory=dict)

    @property
    def is_write(self) -> bool:
        """Whether this intent involves a write or execute operation."""
        return self.action in (IntentAction.WRITE, IntentAction.EXECUTE)

    @property
    def needs_clarification(self) -> bool:
        """Whether this intent has ambiguities requiring user clarification."""
        return self.action == IntentAction.CLARIFY or len(self.ambiguities) > 0


class IntentScope(BaseModel):
    """Declarative scope for allowed and denied intents on an endpoint.

    Uses wildcard matching (e.g., "order.*" matches "order.create").

    Attributes:
        allowed_intents: Patterns of allowed intents. ["*"] means all allowed.
        denied_intents: Patterns of denied intents. Takes precedence over allowed.
    """

    model_config = {"extra": "forbid"}

    allowed_intents: list[str] = Field(default_factory=lambda: ["*"])
    denied_intents: list[str] = Field(default_factory=list)

    def matches(self, intent: Intent) -> bool:
        """Check whether an intent is allowed by this scope.

        Denied patterns take precedence over allowed patterns.
        The intent key used for matching is "{domain}.{action}".

        Args:
            intent: The intent to check.

        Returns:
            True if the intent is allowed by this scope.
        """
        intent_key = f"{intent.domain}.{intent.action}"

        # Check denied first (takes precedence)
        for pattern in self.denied_intents:
            if fnmatch(intent_key, pattern):
                return False

        # Check allowed
        return any(fnmatch(intent_key, pattern) for pattern in self.allowed_intents)


# Keyword maps for simple keyword-based parsing (no LLM)
_READ_KEYWORDS: set[str] = {
    "show",
    "get",
    "list",
    "fetch",
    "read",
    "find",
    "search",
    "query",
    "count",
    "display",
    "view",
    "retrieve",
    "lookup",
    "check",
    "see",
    "表示",
    "取得",
    "一覧",
    "検索",
    "確認",
    "教えて",
    "見せて",
}
_WRITE_KEYWORDS: set[str] = {
    "create",
    "add",
    "insert",
    "update",
    "modify",
    "change",
    "set",
    "put",
    "delete",
    "remove",
    "cancel",
    "disable",
    "enable",
    "作成",
    "追加",
    "更新",
    "変更",
    "削除",
    "キャンセル",
}
_ANALYZE_KEYWORDS: set[str] = {
    "analyze",
    "analyse",
    "report",
    "summarize",
    "compare",
    "trend",
    "statistics",
    "aggregate",
    "correlate",
    "predict",
    "forecast",
    "分析",
    "レポート",
    "集計",
    "傾向",
    "統計",
    "比較",
    "予測",
}
_EXECUTE_KEYWORDS: set[str] = {
    "run",
    "execute",
    "trigger",
    "start",
    "launch",
    "deploy",
    "migrate",
    "実行",
    "起動",
    "デプロイ",
}

# Simple word extraction pattern
_WORD_PATTERN = re.compile(r"[a-zA-Z\u3040-\u9fff]+")


class IntentParser:
    """Parses raw natural language into Intent objects.

    Can operate in two modes:
    - Without LLM: basic keyword-based parsing for action classification
      and simple domain extraction.
    - With LLM: uses structured prompts for accurate classification
      and parameter extraction.

    Example:
        parser = IntentParser()
        intent = await parser.parse("Show me this month's order count")
        assert intent.action == IntentAction.READ

        parser_llm = IntentParser(llm=backend)
        intent = await parser_llm.parse("Cancel order #1234")
        assert intent.action == IntentAction.WRITE
    """

    def __init__(self, *, llm: LLMBackend | None = None) -> None:
        """Initialize the intent parser.

        Args:
            llm: Optional LLM backend for advanced parsing. If None,
                falls back to keyword-based parsing.
        """
        self._llm = llm

    async def parse(
        self,
        raw: str,
        *,
        session_context: dict[str, Any] | None = None,
    ) -> Intent:
        """Parse a natural language request into an Intent.

        Args:
            raw: The raw natural language request string.
            session_context: Optional accumulated session context.

        Returns:
            A parsed Intent object.

        Raises:
            IntentParseError: If parsing fails completely.
        """
        if not raw or not raw.strip():
            raise IntentParseError("Empty intent string")

        ctx = session_context or {}

        if self._llm is not None:
            return await self._parse_with_llm(raw, ctx)
        return self._parse_with_keywords(raw, ctx)

    async def _parse_with_llm(
        self,
        raw: str,
        session_context: dict[str, Any],
    ) -> Intent:
        """Parse intent using the LLM backend.

        Args:
            raw: The raw request string.
            session_context: Session context dict.

        Returns:
            Parsed Intent.

        Raises:
            IntentParseError: If LLM call or JSON parsing fails.
        """
        prompt = build_intent_parsing_prompt(raw)
        assert self._llm is not None  # Guaranteed by caller

        try:
            response = await self._llm.generate(prompt)
        except Exception as exc:
            logger.error("intent_parse_llm_failed", error=str(exc), raw=raw[:200])
            raise IntentParseError(f"LLM call failed during intent parsing: {exc}") from exc

        try:
            parsed = _parse_llm_json(response.content)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "intent_parse_json_failed",
                raw_response=response.content[:200],
                error=str(exc),
            )
            # Fall back to keyword parsing if JSON extraction fails
            fallback_intent = self._parse_with_keywords(raw, session_context)
            return Intent(
                raw=fallback_intent.raw,
                action=fallback_intent.action,
                domain=fallback_intent.domain,
                parameters=fallback_intent.parameters,
                confidence=fallback_intent.confidence,
                ambiguities=[*fallback_intent.ambiguities, f"LLM parsing failed: {exc}; used keyword fallback"],
                session_context=fallback_intent.session_context,
            )

        action_str = parsed.get("action", "read")
        try:
            action = IntentAction(action_str)
        except ValueError:
            action = IntentAction.READ

        domain = parsed.get("domain", "general")
        parameters = parsed.get("parameters", {})
        confidence = float(parsed.get("confidence", 0.8))
        ambiguities = parsed.get("ambiguities", [])

        intent = Intent(
            raw=raw,
            action=action,
            domain=domain,
            parameters=parameters if isinstance(parameters, dict) else {},
            confidence=max(0.0, min(1.0, confidence)),
            ambiguities=ambiguities if isinstance(ambiguities, list) else [],
            session_context=session_context,
        )

        logger.info(
            "intent_parsed",
            intent_action=intent.action,
            intent_domain=intent.domain,
            confidence=intent.confidence,
            ambiguity_count=len(intent.ambiguities),
        )

        return intent

    def _parse_with_keywords(
        self,
        raw: str,
        session_context: dict[str, Any],
    ) -> Intent:
        """Parse intent using simple keyword matching.

        Args:
            raw: The raw request string.
            session_context: Session context dict.

        Returns:
            Parsed Intent with keyword-based classification.
        """
        lower = raw.lower()
        words = set(_WORD_PATTERN.findall(lower))

        action = self._classify_action(words)
        domain = self._extract_domain(words)

        intent = Intent(
            raw=raw,
            action=action,
            domain=domain,
            parameters={},
            confidence=0.5,
            ambiguities=[],
            session_context=session_context,
        )

        logger.info(
            "intent_parsed_keywords",
            intent_action=intent.action,
            intent_domain=intent.domain,
            confidence=intent.confidence,
        )

        return intent

    @staticmethod
    def _classify_action(words: set[str]) -> IntentAction:
        """Classify intent action from keyword overlap.

        Args:
            words: Set of lowercase words from the request.

        Returns:
            The best matching IntentAction.
        """
        scores: dict[IntentAction, int] = {
            IntentAction.READ: len(words & _READ_KEYWORDS),
            IntentAction.WRITE: len(words & _WRITE_KEYWORDS),
            IntentAction.ANALYZE: len(words & _ANALYZE_KEYWORDS),
            IntentAction.EXECUTE: len(words & _EXECUTE_KEYWORDS),
        }

        best_action = max(scores, key=lambda k: scores[k])
        if scores[best_action] == 0:
            return IntentAction.READ  # Default

        return best_action

    @staticmethod
    def _extract_domain(words: set[str]) -> str:
        """Extract domain from words using common domain names.

        Args:
            words: Set of lowercase words from the request.

        Returns:
            Extracted domain name or "general".
        """
        known_domains: dict[str, str] = {
            "order": "order",
            "orders": "order",
            "product": "product",
            "products": "product",
            "user": "user",
            "users": "user",
            "customer": "customer",
            "customers": "customer",
            "payment": "payment",
            "payments": "payment",
            "invoice": "invoice",
            "invoices": "invoice",
            "inventory": "inventory",
            "shipping": "shipping",
            "delivery": "shipping",
            "注文": "order",
            "商品": "product",
            "ユーザ": "user",
            "顧客": "customer",
            "支払い": "payment",
        }

        for word in words:
            if word in known_domains:
                return known_domains[word]

        return "general"


def _parse_llm_json(content: str) -> dict[str, Any]:
    """Extract and parse JSON from LLM response content.

    Handles cases where the LLM wraps JSON in markdown code blocks.

    Args:
        content: The raw LLM response content.

    Returns:
        Parsed JSON as a dictionary.

    Raises:
        json.JSONDecodeError: If no valid JSON can be extracted.
    """
    # Try to extract JSON from code blocks first
    json_block = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
    if json_block:
        return dict(json.loads(json_block.group(1).strip()))

    # Try parsing the raw content directly
    stripped = content.strip()
    # Find the first { and last } for robustness
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return dict(json.loads(stripped[start : end + 1]))

    return dict(json.loads(stripped))
