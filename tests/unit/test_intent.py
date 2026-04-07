"""Tests for Intent model and IntentParser."""

from __future__ import annotations

import pytest

from agenticapi.exceptions import IntentParseError
from agenticapi.interface.intent import Intent, IntentAction, IntentParser, IntentScope


class TestIntentAction:
    def test_enum_values(self) -> None:
        assert IntentAction.READ == "read"
        assert IntentAction.WRITE == "write"
        assert IntentAction.ANALYZE == "analyze"
        assert IntentAction.EXECUTE == "execute"
        assert IntentAction.CLARIFY == "clarify"

    def test_from_string(self) -> None:
        assert IntentAction("read") is IntentAction.READ
        assert IntentAction("write") is IntentAction.WRITE


class TestIntent:
    def test_creation_with_defaults(self) -> None:
        intent = Intent(raw="hello", action=IntentAction.READ, domain="general")
        assert intent.raw == "hello"
        assert intent.action == IntentAction.READ
        assert intent.domain == "general"
        assert intent.parameters == {}
        assert intent.confidence == 1.0
        assert intent.ambiguities == []

    def test_is_write_for_write_action(self) -> None:
        intent = Intent(raw="delete order", action=IntentAction.WRITE, domain="order")
        assert intent.is_write is True

    def test_is_write_for_execute_action(self) -> None:
        intent = Intent(raw="run migration", action=IntentAction.EXECUTE, domain="general")
        assert intent.is_write is True

    def test_is_write_false_for_read(self) -> None:
        intent = Intent(raw="show orders", action=IntentAction.READ, domain="order")
        assert intent.is_write is False

    def test_is_write_false_for_analyze(self) -> None:
        intent = Intent(raw="analyze trends", action=IntentAction.ANALYZE, domain="general")
        assert intent.is_write is False

    def test_needs_clarification_with_clarify_action(self) -> None:
        intent = Intent(raw="something", action=IntentAction.CLARIFY, domain="general")
        assert intent.needs_clarification is True

    def test_needs_clarification_with_ambiguities(self) -> None:
        intent = Intent(
            raw="show data",
            action=IntentAction.READ,
            domain="general",
            ambiguities=["Which data?"],
        )
        assert intent.needs_clarification is True

    def test_no_clarification_needed(self) -> None:
        intent = Intent(raw="show orders", action=IntentAction.READ, domain="order")
        assert intent.needs_clarification is False

    def test_frozen(self) -> None:
        intent = Intent(raw="hello", action=IntentAction.READ, domain="general")
        with pytest.raises(AttributeError):
            intent.raw = "changed"  # type: ignore[misc]


class TestIntentScope:
    def test_default_allows_all(self) -> None:
        scope = IntentScope()
        intent = Intent(raw="test", action=IntentAction.READ, domain="order")
        assert scope.matches(intent) is True

    def test_allowed_specific_pattern(self) -> None:
        scope = IntentScope(allowed_intents=["order.*"])
        intent = Intent(raw="test", action=IntentAction.READ, domain="order")
        assert scope.matches(intent) is True

    def test_denied_pattern_takes_precedence(self) -> None:
        scope = IntentScope(allowed_intents=["*"], denied_intents=["order.write"])
        intent = Intent(raw="delete order", action=IntentAction.WRITE, domain="order")
        assert scope.matches(intent) is False

    def test_denied_does_not_block_unrelated(self) -> None:
        scope = IntentScope(allowed_intents=["*"], denied_intents=["order.write"])
        intent = Intent(raw="show orders", action=IntentAction.READ, domain="order")
        assert scope.matches(intent) is True

    def test_not_in_allowed_list(self) -> None:
        scope = IntentScope(allowed_intents=["product.*"])
        intent = Intent(raw="test", action=IntentAction.READ, domain="order")
        assert scope.matches(intent) is False

    def test_wildcard_denied(self) -> None:
        scope = IntentScope(allowed_intents=["*"], denied_intents=["*.write"])
        intent = Intent(raw="test", action=IntentAction.WRITE, domain="order")
        assert scope.matches(intent) is False


class TestIntentParser:
    async def test_parse_empty_raises(self) -> None:
        parser = IntentParser()
        with pytest.raises(IntentParseError, match="Empty"):
            await parser.parse("")

    async def test_parse_whitespace_only_raises(self) -> None:
        parser = IntentParser()
        with pytest.raises(IntentParseError, match="Empty"):
            await parser.parse("   ")

    async def test_parse_read_keywords(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("show me all orders")
        assert intent.action == IntentAction.READ
        assert intent.domain == "order"

    async def test_parse_write_keywords(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("delete the order")
        assert intent.action == IntentAction.WRITE
        assert intent.domain == "order"

    async def test_parse_analyze_keywords(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("analyze order trends")
        assert intent.action == IntentAction.ANALYZE

    async def test_parse_execute_keywords(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("run the deployment")
        assert intent.action == IntentAction.EXECUTE

    async def test_parse_defaults_to_read(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("something random")
        assert intent.action == IntentAction.READ

    async def test_parse_confidence_is_half_without_llm(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("show orders")
        assert intent.confidence == 0.5

    async def test_parse_domain_extraction(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("show all products")
        assert intent.domain == "product"

    async def test_parse_unknown_domain(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("do something weird")
        assert intent.domain == "general"

    async def test_parse_japanese_read(self) -> None:
        parser = IntentParser()
        intent = await parser.parse("注文を教えて")
        assert intent.action == IntentAction.READ

    async def test_parse_japanese_write(self) -> None:
        parser = IntentParser()
        # Use "削除" as a standalone word (space-separated) so keyword matching works
        intent = await parser.parse("注文 削除")
        assert intent.action == IntentAction.WRITE

    async def test_parse_preserves_session_context(self) -> None:
        parser = IntentParser()
        ctx = {"previous": "data"}
        intent = await parser.parse("show orders", session_context=ctx)
        assert intent.session_context == ctx
