# LLM Backends

## LLMBackend (Protocol)

::: agenticapi.runtime.llm.base.LLMBackend

## Data Classes

::: agenticapi.runtime.llm.base.LLMPrompt

::: agenticapi.runtime.llm.base.LLMMessage

`LLMMessage` carries two optional fields for multi-turn tool conversations:

- **`tool_call_id: str | None`** — on `role="tool"` messages, links back to the originating tool call. Required by OpenAI, used by Anthropic for `tool_result` blocks.
- **`tool_calls: list[ToolCall] | None`** — on `role="assistant"` messages, preserves the full tool call structure so backends can reconstruct provider-native multi-turn formats.

Both fields default to `None` for backward compatibility.

::: agenticapi.runtime.llm.base.LLMResponse

`LLMResponse` carries two fields that drive native function calling:

- **`tool_calls: list[ToolCall]`** — structured function-call requests returned by the model. Empty for plain text completions.
- **`finish_reason: str | None`** — why generation stopped. Typical values: `"stop"`, `"length"`, `"tool_calls"`, `"content_filter"`. `None` for backends that don't report it.

All four backends (Anthropic, OpenAI, Gemini, Mock) fully populate these fields. Each real backend parses its provider's native response format into `ToolCall` objects and maps stop reasons to normalized `finish_reason` values.

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

## RetryConfig

::: agenticapi.runtime.llm.retry.RetryConfig

## CodeGenerator

::: agenticapi.runtime.code_generator.CodeGenerator
