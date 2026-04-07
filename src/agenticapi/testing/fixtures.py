"""pytest fixtures and test helpers for AgenticAPI.

Provides factory functions for creating pre-configured test instances
of AgenticApp and related components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agenticapi.app import AgenticApp
from agenticapi.harness.engine import HarnessEngine
from agenticapi.runtime.llm.mock import MockBackend

if TYPE_CHECKING:
    from agenticapi.harness.policy.base import Policy


def create_test_app(
    *,
    policies: list[Policy] | None = None,
    llm_responses: list[str] | None = None,
    title: str = "TestApp",
) -> AgenticApp:
    """Create an AgenticApp configured for testing.

    Builds an app with optional mock LLM backend and harness engine.
    Useful for integration tests that need a fully wired application.

    Args:
        policies: Optional list of policies for the harness engine.
        llm_responses: Optional list of LLM response strings. If provided,
            a MockBackend is created and a HarnessEngine is configured.
        title: Application title (default "TestApp").

    Returns:
        A configured AgenticApp ready for testing.

    Example:
        app = create_test_app(
            policies=[CodePolicy(denied_modules=["os"])],
            llm_responses=["SELECT COUNT(*) FROM orders"],
        )

        @app.agent_endpoint(name="test")
        async def test_agent(intent, context):
            return {"result": "ok"}

        response = await app.process_intent("show orders")
    """
    llm: MockBackend | None = None
    harness: HarnessEngine | None = None

    if llm_responses is not None:
        llm = MockBackend(responses=llm_responses)

    if policies is not None or llm is not None:
        harness = HarnessEngine(policies=policies)

    return AgenticApp(
        title=title,
        harness=harness,
        llm=llm,  # type: ignore[arg-type]  # MockBackend satisfies LLMBackend Protocol
    )
