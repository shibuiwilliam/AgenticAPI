"""Regression tests for bug fixes identified in code review.

Each test targets a specific bug fix to prevent regressions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agenticapi.exceptions import ToolError
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.harness.sandbox.static_analysis import check_code_safety
from agenticapi.runtime.context import AgentContext
from agenticapi.runtime.tools.database import DatabaseTool


class TestFix1EngineUsesConfiguredSandbox:
    """Fix 1: HarnessEngine must use the sandbox passed to __init__."""

    async def test_engine_uses_injected_sandbox(self) -> None:
        """Verify the engine calls the injected sandbox, not a new one."""
        mock_sandbox = MagicMock()
        mock_sandbox.__aenter__ = AsyncMock(return_value=mock_sandbox)
        mock_sandbox.__aexit__ = AsyncMock(return_value=None)
        mock_sandbox.execute = AsyncMock(
            return_value=MagicMock(
                return_value=42,
                output="ok",
                metrics=MagicMock(cpu_time_ms=1, memory_peak_mb=1, wall_time_ms=1),
                stdout="",
                stderr="",
            )
        )

        engine = HarnessEngine(policies=[], sandbox=mock_sandbox)
        context = AgentContext(trace_id="test", endpoint_name="test")

        result = await engine.execute(
            intent_raw="test",
            intent_action="read",
            intent_domain="general",
            generated_code="result = 42",
            endpoint_name="test",
            context=context,
        )

        # The injected sandbox should have been used
        mock_sandbox.__aenter__.assert_called_once()
        mock_sandbox.execute.assert_called_once()
        assert result.output == 42


class TestFix3StaticAnalysisAttributeBypass:
    """Fix 3: Static analysis must detect attribute-based dangerous calls."""

    def test_detects_builtins_eval_via_attribute(self) -> None:
        code = "x = builtins.eval('1+1')"
        result = check_code_safety(code, deny_eval_exec=True)
        assert not result.safe
        assert any("eval" in v.description for v in result.violations)

    def test_detects_obj_exec_via_attribute(self) -> None:
        code = "obj.exec('code')"
        result = check_code_safety(code, deny_eval_exec=True)
        assert not result.safe
        assert any("exec" in v.description for v in result.violations)

    def test_detects_module_import_via_attribute(self) -> None:
        code = "builtins.__import__('os')"
        result = check_code_safety(code, deny_dynamic_import=True)
        assert not result.safe
        assert any("__import__" in v.description for v in result.violations)

    def test_detects_open_via_attribute(self) -> None:
        code = "builtins.open('/etc/passwd')"
        result = check_code_safety(code)
        assert not result.safe
        assert any("open" in v.description for v in result.violations)


class TestFix4DatabaseCommentBypass:
    """Fix 4: SQL write detection must work despite comments."""

    def test_line_comment_before_delete(self) -> None:
        assert DatabaseTool._is_write_query("-- comment\nDELETE FROM users")

    def test_block_comment_before_insert(self) -> None:
        assert DatabaseTool._is_write_query("/* comment */ INSERT INTO users VALUES (1)")

    def test_multiline_comment_before_update(self) -> None:
        assert DatabaseTool._is_write_query("/*\nmulti\nline\n*/\nUPDATE users SET x=1")

    def test_select_with_comment_still_allowed(self) -> None:
        assert not DatabaseTool._is_write_query("-- get users\nSELECT * FROM users")

    async def test_read_only_blocks_commented_write(self) -> None:
        tool = DatabaseTool(
            execute_fn=AsyncMock(return_value=[]),
            read_only=True,
        )
        with pytest.raises(ToolError, match="read-only"):
            await tool.invoke(query="-- harmless\nDELETE FROM users")


class TestFix5SessionMemoryLeak:
    """Fix 5: Expired sessions must be cleaned up periodically."""

    async def test_cleanup_removes_expired_sessions(self) -> None:
        from agenticapi.interface.session import SessionManager

        manager = SessionManager(ttl_seconds=1)

        # Create a session
        session = await manager.get_or_create("s1")
        assert manager.active_count == 1

        # Manually expire it
        from datetime import UTC, datetime, timedelta

        session.last_accessed = datetime.now(tz=UTC) - timedelta(seconds=10)

        # Run cleanup
        manager._cleanup_expired()

        # Session should be removed
        result = await manager.get("s1")
        assert result is None


class TestFix7IntentParserFallbackLogging:
    """Fix 7: IntentParser LLM fallback must indicate in ambiguities."""

    async def test_fallback_intent_has_ambiguity_note(self) -> None:
        from agenticapi.interface.intent import IntentParser
        from agenticapi.runtime.llm.mock import MockBackend

        # Mock LLM returns invalid JSON
        mock = MockBackend(responses=["not valid json at all"])
        parser = IntentParser(llm=mock)

        intent = await parser.parse("show orders")

        # Should fall back to keywords, with ambiguity noting the failure
        assert any("LLM parsing failed" in a for a in intent.ambiguities)
        assert intent.confidence == 0.5  # Keyword fallback confidence


class TestFix8RestCompatIntentSizeLimit:
    """Fix 8: REST compat must reject oversized intents."""

    def test_get_rejects_oversized_query(self) -> None:
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from agenticapi.app import AgenticApp
        from agenticapi.interface.compat.rest import expose_as_rest

        app = AgenticApp()

        @app.agent_endpoint(name="test")
        async def handler(intent, context):  # type: ignore[no-untyped-def]
            return {}

        routes = expose_as_rest(app)
        starlette_app = Starlette(routes=routes)
        client = TestClient(starlette_app)

        huge_query = "x" * 20_000
        response = client.get(f"/rest/test?query={huge_query}")
        assert response.status_code == 400
        assert "too long" in response.json()["error"]


class TestFix9CodeGeneratorFirstBlock:
    """Fix 9: Code generator must return first code block, not longest."""

    def test_returns_first_not_longest(self) -> None:
        from agenticapi.runtime.code_generator import _extract_code

        output = (
            "```python\nresult = 42\n```\n\n```python\n# This is a very long comment block\n# " + "x" * 500 + "\n```"
        )
        code = _extract_code(output)
        assert code == "result = 42"


class TestFix12DataPolicyQuotedIdentifiers:
    """Fix 12: DataPolicy must detect quoted table.column references."""

    def test_backtick_quoted_column_detected(self) -> None:
        policy = DataPolicy(restricted_columns=["users.password_hash"])
        result = policy.evaluate(code="SELECT `users`.`password_hash` FROM users")
        assert result.allowed is False

    def test_double_quote_column_detected(self) -> None:
        policy = DataPolicy(restricted_columns=["users.password_hash"])
        result = policy.evaluate(code='SELECT "users"."password_hash" FROM users')
        assert result.allowed is False

    def test_unquoted_column_still_detected(self) -> None:
        policy = DataPolicy(restricted_columns=["users.password_hash"])
        result = policy.evaluate(code="SELECT users.password_hash FROM users")
        assert result.allowed is False
