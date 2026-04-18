# LLM Backends

AgenticAPI supports multiple LLM providers through a pluggable `LLMBackend` protocol. All built-in backends support text generation, streaming, native function calling, and automatic retry with exponential backoff.

## Built-in Backends

| Backend | Provider | Default Model | Env Variable |
|---|---|---|---|
| `AnthropicBackend` | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `OpenAIBackend` | OpenAI | `gpt-5.4-mini` | `OPENAI_API_KEY` |
| `GeminiBackend` | Google | `gemini-2.5-flash` | `GOOGLE_API_KEY` |
| `MockBackend` | (Testing) | `mock` | -- |

## Capability Matrix

| Backend | Text | Stream | Native Tool Calls | `finish_reason` | `tool_choice` | Retry |
|---|---|---|---|---|---|---|
| `AnthropicBackend` | Yes | Yes | Yes | Yes | Yes | RateLimitError, Timeout, 5xx |
| `OpenAIBackend` | Yes | Yes | Yes | Yes | Yes | RateLimitError, Timeout |
| `GeminiBackend` | Yes | Yes | Yes | Yes | Yes | ResourceExhausted, Unavailable |
| `MockBackend` | Yes | Yes | Yes | Yes | Yes | -- |

```python
from agenticapi.runtime.llm import AnthropicBackend, OpenAIBackend, GeminiBackend

llm = AnthropicBackend(model="claude-sonnet-4-6")
llm = OpenAIBackend(model="gpt-5.4-mini")
llm = GeminiBackend(model="gemini-2.5-flash")
```

## Usage

### Complete Generation

```python
from agenticapi.runtime.llm.base import LLMPrompt, LLMMessage

response = await backend.generate(LLMPrompt(
    system="You are a helpful assistant.",
    messages=[LLMMessage(role="user", content="Write a SQL query")],
))
print(response.content)
print(response.usage)  # LLMUsage(input_tokens=..., output_tokens=...)
```

### Streaming

```python
async for chunk in backend.generate_stream(prompt):
    print(chunk.content, end="")
```

## Structured Output

`LLMPrompt` supports `response_schema` for typed-intent and structured-output use cases. `MockBackend` fully honors `response_schema` and synthesises schema-conforming JSON. The provider backends do not yet translate `response_schema` into provider-native structured-output APIs, but the typed-intent programming model works end-to-end with `MockBackend`.

## Native Function Calling

All four backends support native function calling. The LLM receives tool definitions, decides when to call them, and returns structured `ToolCall` objects. AgenticAPI's tool-first execution path (E4) dispatches these calls through the harness without going through the sandbox.

```python
from agenticapi.runtime.llm.base import LLMMessage, LLMPrompt

prompt = LLMPrompt(
    system="You answer questions about orders.",
    messages=[LLMMessage(role="user", content="How many shipped orders today?")],
    tools=[
        {
            "name": "count_orders",
            "description": "Count orders by status.",
            "parameters": {
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
        }
    ],
    tool_choice="auto",  # or "required", "none", {"type": "tool", "name": "..."}
)

response = await backend.generate(prompt)

if response.finish_reason == "tool_calls":
    for call in response.tool_calls:
        print(call.id, call.name, call.arguments)
        result = await registry.get(call.name).invoke(**call.arguments)
else:
    print(response.content)
```

### `tool_choice`

Controls how the model selects tools:

| Value | Meaning |
|---|---|
| `"auto"` | Model decides whether to call a tool or respond with text |
| `"required"` | Model must call at least one tool |
| `"none"` | Model must not call any tool |
| `{"type": "tool", "name": "count_orders"}` | Force a specific tool |
| `None` | Defer to the provider's default (usually `"auto"`) |

Each backend translates `tool_choice` into its provider's native format (Anthropic uses `{"type": "any"}` for `"required"`, Gemini uses `FunctionCallingConfig(mode="ANY")`, etc.).

### `ToolCall`

```python
@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str                    # provider-supplied call ID
    name: str                  # tool name to invoke
    arguments: dict[str, Any]  # parsed keyword arguments
```

### `LLMResponse.finish_reason`

`finish_reason` reports why generation stopped:

| Value | Meaning |
|---|---|
| `"stop"` | Natural end of turn |
| `"length"` | `max_tokens` reached |
| `"tool_calls"` | Model requested tool(s); inspect `tool_calls` |
| `"content_filter"` | Provider's safety filter engaged |
| `None` | Backend didn't report a finish reason |

## Retry

All real backends include automatic retry with exponential backoff for transient provider errors. Each backend ships sensible defaults (3 retries, 1s base delay, jitter enabled). You can customize via `RetryConfig`:

```python
from agenticapi.runtime.llm.retry import RetryConfig

backend = AnthropicBackend(
    retry=RetryConfig(
        max_retries=5,
        base_delay_seconds=0.5,
        max_delay_seconds=60.0,
        jitter=True,
    ),
)
```

`RetryConfig` fields:

| Field | Default | Purpose |
|---|---|---|
| `max_retries` | 3 | Maximum retry attempts (0 = no retries) |
| `base_delay_seconds` | 1.0 | Initial delay before first retry |
| `max_delay_seconds` | 30.0 | Upper bound on delay |
| `jitter` | `True` | Add randomness to prevent thundering herd |
| `retryable_exceptions` | Provider-specific | Exception types that trigger retry |

## Custom Backend

Any class matching the `LLMBackend` protocol works without inheriting from AgenticAPI:

```python
class MyCustomBackend:
    async def generate(self, prompt: LLMPrompt) -> LLMResponse: ...
    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]: ...
    @property
    def model_name(self) -> str: ...
```

To support native function calling, populate `LLMResponse.tool_calls` and `LLMResponse.finish_reason` from your provider's response format.

## MockBackend for Testing

```python
from agenticapi.runtime.llm.base import ToolCall
from agenticapi.runtime.llm.mock import MockBackend

backend = MockBackend(responses=["SELECT COUNT(*) FROM orders", "result = 42"])
response = await backend.generate(prompt)
assert response.content == "SELECT COUNT(*) FROM orders"
assert backend.call_count == 1

# Queue a native tool-call response for the next tools-enabled request:
backend.add_tool_call_response([
    ToolCall(id="call_1", name="count_orders", arguments={"status": "shipped"}),
])
```

When `MockBackend.generate()` receives a prompt with `tools` and a tool-call response is queued, it returns the queued `ToolCall`s with `finish_reason="tool_calls"`. When no tool-call response is queued, it falls back to the next text response. If `tool_choice="required"`, it synthesises a call to the first declared tool even when no response is queued.

## Multi-Turn Tool Conversations

For multi-turn tool conversations (e.g. the agentic loop), `LLMMessage`
carries two optional fields for provider-native format translation:

```python
from agenticapi.runtime.llm.base import LLMMessage, ToolCall

# Assistant message with tool calls
assistant_msg = LLMMessage(
    role="assistant",
    content="Let me calculate that.",
    tool_calls=[ToolCall(id="call_1", name="calc", arguments={"expr": "7*6"})],
)

# Tool result linked back to the call
tool_msg = LLMMessage(
    role="tool",
    content='{"result": 42}',
    tool_call_id="call_1",
)
```

Each backend translates these into provider-native format:

| Provider | Assistant Tool Calls | Tool Results |
|---|---|---|
| **Anthropic** | `tool_use` content blocks with `id`, `name`, `input` | `user` message with `tool_result` block keyed by `tool_use_id` |
| **OpenAI** | `tool_calls` array with `function` objects (JSON-encoded args) | `tool` role with `tool_call_id` |
| **Gemini** | `function_call` Parts on `model` message | `function_response` Parts on `user` message (name resolved to actual function name) |

The agentic loop (`run_agentic_loop()` and `run_agentic_loop_streaming()`)
automatically populates these fields on every iteration.

## Integration Testing with Real Providers

Integration tests verify end-to-end tool calling against real APIs:

```bash
# Run when API keys are available (skipped otherwise)
ANTHROPIC_API_KEY=sk-... OPENAI_API_KEY=sk-... GOOGLE_API_KEY=... \
  uv run pytest tests/integration/llm/ -v --timeout=60
```

Each test sends a calculator tool definition, asserts the LLM calls the tool,
sends the result back, and asserts the final answer contains "42".
