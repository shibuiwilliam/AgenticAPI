"""Base test case for AgenticAPI applications.

Provides a pytest-compatible base class with pre-wired AgenticApp,
mock LLM, and harness engine for writing agent tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agenticapi.app import AgenticApp
from agenticapi.harness.engine import HarnessEngine
from agenticapi.interface.intent import IntentAction
from agenticapi.interface.response import AgentResponse
from agenticapi.runtime.llm.mock import MockBackend
from agenticapi.testing.assertions import assert_code_safe, assert_intent_parsed, assert_policy_enforced

if TYPE_CHECKING:
    from agenticapi.harness.policy.base import Policy


class AgentTestCase:
    """Base test class for AgenticAPI agent tests.

    Provides a pre-wired AgenticApp with optional MockBackend and
    HarnessEngine, plus helper methods for common assertions.

    Usage with pytest:
        class TestMyAgent(AgentTestCase):
            def setup_method(self):
                self.setup_app(
                    policies=[CodePolicy(denied_modules=["os"])],
                    llm_responses=["result = 42"],
                )

            async def test_process_intent(self):
                response = await self.process_intent("count orders")
                assert response.status == "completed"

    Or use setup_app() in individual tests for different configurations.
    """

    app: AgenticApp
    mock_backend: MockBackend | None

    def setup_app(
        self,
        *,
        title: str = "TestApp",
        policies: list[Policy] | None = None,
        llm_responses: list[str] | None = None,
    ) -> AgenticApp:
        """Set up a test AgenticApp with optional harness and mock LLM.

        Args:
            title: Application title.
            policies: Optional harness policies.
            llm_responses: Optional mock LLM responses. If provided,
                a MockBackend is created and wired to the app.

        Returns:
            The configured AgenticApp.
        """
        self.mock_backend = None
        llm = None
        harness = None

        if llm_responses is not None:
            self.mock_backend = MockBackend(responses=llm_responses)
            llm = self.mock_backend

        if policies is not None or llm is not None:
            harness = HarnessEngine(policies=policies)

        self.app = AgenticApp(title=title, harness=harness, llm=llm)  # type: ignore[arg-type]
        return self.app

    async def process_intent(
        self,
        raw_request: str,
        *,
        endpoint_name: str | None = None,
        session_id: str | None = None,
    ) -> AgentResponse:
        """Process a natural language request through the test app.

        Args:
            raw_request: The natural language request.
            endpoint_name: Optional endpoint to target.
            session_id: Optional session ID.

        Returns:
            The AgentResponse from processing.
        """
        result = await self.app.process_intent(
            raw_request,
            endpoint_name=endpoint_name,
            session_id=session_id,
        )
        assert isinstance(result, AgentResponse), f"Expected AgentResponse, got {type(result)}"
        return result

    def get_audit_records(
        self,
        *,
        endpoint_name: str | None = None,
        limit: int = 100,
    ) -> list[Any]:
        """Get audit records from the harness engine.

        Args:
            endpoint_name: Optional filter by endpoint name.
            limit: Maximum number of records to return.

        Returns:
            List of ExecutionTrace objects.
        """
        if self.app.harness is None:
            return []
        return self.app.harness.audit_recorder.get_records(
            endpoint_name=endpoint_name,
            limit=limit,
        )

    def assert_intent(self, raw: str, expected_action: IntentAction | str) -> None:
        """Assert that a raw request parses to the expected action.

        Args:
            raw: The raw natural language request.
            expected_action: The expected IntentAction value.
        """
        action = expected_action if isinstance(expected_action, IntentAction) else IntentAction(expected_action)
        assert_intent_parsed(raw, action)

    def assert_safe_code(self, code: str, *, denied_modules: list[str] | None = None) -> None:
        """Assert that code passes static safety analysis.

        Args:
            code: The Python code to check.
            denied_modules: Optional modules to deny.
        """
        assert_code_safe(code, denied_modules=denied_modules)

    def assert_policies(self, code: str, policies: list[Policy]) -> None:
        """Assert that code passes policy evaluation.

        Args:
            code: The Python code to check.
            policies: The policies to evaluate against.
        """
        assert_policy_enforced(code, policies)
