"""Tests for AgentTestCase."""

from __future__ import annotations

import pytest

from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.interface.intent import IntentAction
from agenticapi.testing.agent_test_case import AgentTestCase


class TestAgentTestCaseSetup(AgentTestCase):
    def test_setup_app_creates_app(self) -> None:
        self.setup_app()
        assert self.app is not None
        assert self.app.title == "TestApp"

    def test_setup_app_with_custom_title(self) -> None:
        self.setup_app(title="Custom")
        assert self.app.title == "Custom"

    def test_setup_app_without_llm(self) -> None:
        self.setup_app()
        assert self.mock_backend is None

    def test_setup_app_with_llm_responses(self) -> None:
        self.setup_app(llm_responses=["result = 1"])
        assert self.mock_backend is not None


class TestAgentTestCaseIntentAssertion(AgentTestCase):
    def test_assert_intent_read(self) -> None:
        self.setup_app()
        self.assert_intent("show orders", IntentAction.READ)

    def test_assert_intent_write(self) -> None:
        self.setup_app()
        self.assert_intent("delete order", IntentAction.WRITE)

    def test_assert_intent_string_action(self) -> None:
        self.setup_app()
        self.assert_intent("show data", "read")


class TestAgentTestCaseCodeAssertions(AgentTestCase):
    def test_assert_safe_code_passes(self) -> None:
        self.setup_app()
        self.assert_safe_code("x = 1 + 2")

    def test_assert_safe_code_fails_on_os(self) -> None:
        self.setup_app()
        with pytest.raises(AssertionError):
            self.assert_safe_code("import os", denied_modules=["os"])

    def test_assert_policies_passes(self) -> None:
        self.setup_app()
        self.assert_policies("x = 1", [CodePolicy(denied_modules=["os"])])

    def test_assert_policies_fails(self) -> None:
        self.setup_app()
        with pytest.raises(AssertionError):
            self.assert_policies("import os", [CodePolicy(denied_modules=["os"])])


class TestAgentTestCaseProcessIntent(AgentTestCase):
    async def test_process_intent_with_handler(self) -> None:
        self.setup_app()

        @self.app.agent_endpoint(name="test")
        async def handler(intent, context):  # type: ignore[no-untyped-def]
            return {"message": "ok"}

        response = await self.process_intent("hello")
        assert response.status == "completed"
        assert response.result == {"message": "ok"}


class TestAgentTestCaseAuditRecords(AgentTestCase):
    def test_get_audit_records_without_harness(self) -> None:
        self.setup_app()
        records = self.get_audit_records()
        assert records == []
