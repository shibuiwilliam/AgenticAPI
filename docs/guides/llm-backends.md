# LLM Backends

AgenticAPI supports multiple LLM providers through a pluggable `LLMBackend` protocol.

## Built-in Backends

| Backend | Provider | Default Model | Env Variable |
|---|---|---|---|
| `AnthropicBackend` | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `OpenAIBackend` | OpenAI | `gpt-5.4-mini` | `OPENAI_API_KEY` |
| `GeminiBackend` | Google | `gemini-2.5-flash` | `GOOGLE_API_KEY` |
| `MockBackend` | (Testing) | `mock` | — |

## Capability Matrix

The protocol supports structured output and native tool calling, but the built-in backends are not all at the same integration level today.

| Backend | Text generate | Stream | Forwards `prompt.tools` | Honors `response_schema` | Populates `tool_calls` / `finish_reason` |
|---|---|---|---|---|---|
| `AnthropicBackend` | Yes | Yes | Yes | No | No |
| `OpenAIBackend` | Yes | Yes | Yes | No | No |
| `GeminiBackend` | Yes | Yes | No | No | No |
| `MockBackend` | Yes | Yes | Yes | Yes | Yes |

Custom backends can implement the full contract immediately by returning `LLMResponse` objects with `tool_calls`, `finish_reason`, and schema-conforming `content`.

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

`LLMPrompt` supports `response_schema` for typed-intent and structured-output use cases. Today:

- `MockBackend` fully honors `response_schema`
- the built-in provider backends do not yet translate `response_schema` into provider-native structured-output APIs

That means the typed-intent programming model is real, but provider-side schema enforcement is still partial unless you use `MockBackend` or a custom backend that implements it.

## Custom Backend

Any class matching the `LLMBackend` protocol works without inheriting from AgenticAPI:

```python
class MyCustomBackend:
    async def generate(self, prompt: LLMPrompt) -> LLMResponse: ...
    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]: ...
    @property
    def model_name(self) -> str: ...
```

## Native Function Calling

The protocol supports structured function-call objects via `ToolCall` and `LLMResponse.tool_calls`. `MockBackend` fully exercises that contract today, and `AgenticApp` has a tool-first execution path that can dispatch a single tool call directly through the harness. The built-in provider backends still need response normalization before they expose this behavior consistently.

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
)

response = await backend.generate(prompt)

if response.tool_calls:
    for call in response.tool_calls:
        print(call.id, call.name, call.arguments)
        # Dispatch to your tool registry:
        result = await registry.get(call.name).invoke(**call.arguments)
else:
    print(response.content)
```

### `ToolCall`

```python
@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str                    # provider-supplied call ID (echo back for tool-result messages)
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

Today, `MockBackend` fully populates these fields. The built-in provider backends still return text-first `LLMResponse` objects and do not yet normalize provider-native tool-call payloads or finish reasons into the shared contract.

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

When `MockBackend.generate()` receives a `prompt.tools` and a tool-call response is queued, it returns the queued `ToolCall`s. When no tool-call response is queued, it falls back to the next text/structured response in the regular queue.
