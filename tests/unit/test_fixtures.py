"""Tests for testing fixtures."""

from __future__ import annotations

from agenticapi.app import AgenticApp
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.testing.fixtures import create_test_app


class TestCreateTestApp:
    def test_creates_basic_app(self) -> None:
        app = create_test_app()
        assert isinstance(app, AgenticApp)
        assert app.title == "TestApp"
        assert app.harness is None

    def test_custom_title(self) -> None:
        app = create_test_app(title="Custom")
        assert app.title == "Custom"

    def test_with_policies_creates_harness(self) -> None:
        app = create_test_app(policies=[CodePolicy()])
        assert app.harness is not None

    def test_with_llm_responses_creates_harness(self) -> None:
        app = create_test_app(llm_responses=["SELECT 1"])
        assert app.harness is not None

    def test_with_both_policies_and_llm(self) -> None:
        app = create_test_app(
            policies=[CodePolicy(denied_modules=["os"])],
            llm_responses=["SELECT 1"],
        )
        assert app.harness is not None
