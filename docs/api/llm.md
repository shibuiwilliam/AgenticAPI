# LLM Backends

## LLMBackend (Protocol)

::: agenticapi.runtime.llm.base.LLMBackend

## Data Classes

::: agenticapi.runtime.llm.base.LLMPrompt

::: agenticapi.runtime.llm.base.LLMMessage

::: agenticapi.runtime.llm.base.LLMResponse

`LLMResponse` carries two fields that drive native function calling:

- **`tool_calls: list[ToolCall]`** — structured function-call requests returned by the model. Empty for plain text completions.
- **`finish_reason: str | None`** — why generation stopped. Typical values: `"stop"`, `"length"`, `"tool_calls"`, `"content_filter"`. `None` for backends that don't report it.

The protocol supports these fields across all backends. In the current implementation, `MockBackend` fully exercises them; the built-in provider adapters are still partial and mostly return text-first responses.

::: agenticapi.runtime.llm.base.ToolCall

::: agenticapi.runtime.llm.base.LLMUsage

::: agenticapi.runtime.llm.base.LLMChunk

## AnthropicBackend

::: agenticapi.runtime.llm.anthropic.AnthropicBackend

## OpenAIBackend

::: agenticapi.runtime.llm.openai.OpenAIBackend

## GeminiBackend

::: agenticapi.runtime.llm.gemini.GeminiBackend

## MockBackend

::: agenticapi.runtime.llm.mock.MockBackend

## CodeGenerator

::: agenticapi.runtime.code_generator.CodeGenerator
