"""Unit tests for GeminiBackend tool format and multi-turn messages.

Verifies that:
- ``_convert_tools()`` produces ``FunctionDeclaration`` objects.
- Multi-turn messages with tool_calls become ``function_call`` parts.
- Tool result messages become ``function_response`` parts.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt, ToolCall
from agenticapi.runtime.llm.retry import RetryConfig

# ---------------------------------------------------------------------------
# Stub google.genai.types for offline testing
# ---------------------------------------------------------------------------


class _StubFunctionDeclaration:
    def __init__(self, *, name: str = "", description: str = "", parameters: Any = None) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters


class _StubFunctionCall:
    def __init__(self, *, name: str = "", args: dict[str, Any] | None = None) -> None:
        self.name = name
        self.args = args or {}


class _StubFunctionResponse:
    def __init__(self, *, name: str = "", response: dict[str, Any] | None = None) -> None:
        self.name = name
        self.response = response or {}


class _StubPart:
    def __init__(
        self,
        *,
        text: str | None = None,
        function_call: _StubFunctionCall | None = None,
        function_response: _StubFunctionResponse | None = None,
    ) -> None:
        self.text = text
        self.function_call = function_call
        self.function_response = function_response


class _StubContent:
    def __init__(self, *, role: str = "", parts: list[Any] | None = None) -> None:
        self.role = role
        self.parts = parts or []


class _StubTool:
    def __init__(self, *, function_declarations: list[Any] | None = None) -> None:
        self.function_declarations = function_declarations or []


class _StubToolConfig:
    def __init__(self, *, function_calling_config: Any = None) -> None:
        self.function_calling_config = function_calling_config


class _StubFunctionCallingConfig:
    def __init__(self, *, mode: str = "AUTO", allowed_function_names: list[str] | None = None) -> None:
        self.mode = mode
        self.allowed_function_names = allowed_function_names


class _StubGenerateContentConfig:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _StubCandidate:
    def __init__(self, *, content: _StubContent | None = None, finish_reason: str = "STOP") -> None:
        self.content = content or _StubContent()
        self.finish_reason = finish_reason


class _StubUsageMeta:
    prompt_token_count: int = 10
    candidates_token_count: int = 20


class _StubResponse:
    def __init__(self, *, candidates: list[_StubCandidate] | None = None) -> None:
        self.candidates = candidates or [_StubCandidate(content=_StubContent(parts=[_StubPart(text="ok")]))]
        self.usage_metadata = _StubUsageMeta()
        self.text = "ok"


# Build a stub types module
class _StubTypes:
    FunctionDeclaration = _StubFunctionDeclaration
    FunctionCall = _StubFunctionCall
    FunctionResponse = _StubFunctionResponse
    Part = _StubPart
    Content = _StubContent
    Tool = _StubTool
    ToolConfig = _StubToolConfig
    FunctionCallingConfig = _StubFunctionCallingConfig
    GenerateContentConfig = _StubGenerateContentConfig


def _make_backend(client_mock: MagicMock) -> Any:
    with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}):
        from agenticapi.runtime.llm.gemini import GeminiBackend

        backend = GeminiBackend(retry=RetryConfig(max_retries=0, retryable_exceptions=()))
        backend._client = client_mock
        return backend


# ---------------------------------------------------------------------------
# Tool format tests
# ---------------------------------------------------------------------------


class TestGeminiToolFormat:
    """Verify _convert_tools() produces FunctionDeclaration objects."""

    def test_convert_tools_produces_declarations(self) -> None:
        with patch("agenticapi.runtime.llm.gemini.GeminiBackend._convert_tools.__wrapped__", create=True):
            pass
        # Directly test the static method by patching types.
        with patch("google.genai.types", _StubTypes):
            from agenticapi.runtime.llm.gemini import GeminiBackend

            tools = [
                {"name": "calc", "description": "Calculate", "parameters": {"type": "object"}},
                {"name": "search", "description": "Search", "input_schema": {"type": "object"}},
            ]
            result = GeminiBackend._convert_tools(tools)

            assert len(result) == 1  # Single Tool wrapping declarations
            declarations = result[0].function_declarations
            assert len(declarations) == 2
            assert declarations[0].name == "calc"
            assert declarations[1].name == "search"


# ---------------------------------------------------------------------------
# Multi-turn message format tests
# ---------------------------------------------------------------------------


class TestGeminiMultiTurnMessages:
    """Verify multi-turn messages use function_call and function_response parts."""

    async def test_multi_turn_with_tool_calls(self) -> None:
        response = _StubResponse(candidates=[_StubCandidate(content=_StubContent(parts=[_StubPart(text="42")]))])
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=response)

        with patch("google.genai.types", _StubTypes):
            backend = _make_backend(client)

            prompt = LLMPrompt(
                system="test",
                messages=[
                    LLMMessage(role="user", content="What is 7 * 6?"),
                    LLMMessage(
                        role="assistant",
                        content="Let me check.",
                        tool_calls=[ToolCall(id="tc_1", name="calc", arguments={"expr": "7*6"})],
                    ),
                    LLMMessage(role="tool", content='{"result": 42}', tool_call_id="tc_1"),
                ],
            )
            await backend.generate(prompt)

            call_kwargs = client.aio.models.generate_content.call_args[1]
            contents = call_kwargs["contents"]

            # Content 0: user message
            assert contents[0].role == "user"
            assert contents[0].parts[0].text == "What is 7 * 6?"

            # Content 1: model message with function_call part
            assert contents[1].role == "model"
            assert contents[1].parts[0].text == "Let me check."
            fc = contents[1].parts[1].function_call
            assert fc.name == "calc"
            assert fc.args == {"expr": "7*6"}

            # Content 2: user message with function_response part
            # The name must be the *function name* ("calc"), not the
            # call ID ("tc_1"). Gemini requires this for round-trip.
            assert contents[2].role == "user"
            fr = contents[2].parts[0].function_response
            assert fr.name == "calc"
            assert fr.response == {"result": '{"result": 42}'}

    async def test_plain_messages_unchanged(self) -> None:
        response = _StubResponse()
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=response)

        with patch("google.genai.types", _StubTypes):
            backend = _make_backend(client)

            prompt = LLMPrompt(
                system="test",
                messages=[
                    LLMMessage(role="user", content="hi"),
                    LLMMessage(role="assistant", content="hello"),
                ],
            )
            await backend.generate(prompt)

            contents = client.aio.models.generate_content.call_args[1]["contents"]
            assert contents[0].role == "user"
            assert contents[0].parts[0].text == "hi"
            assert contents[1].role == "model"
            assert contents[1].parts[0].text == "hello"
