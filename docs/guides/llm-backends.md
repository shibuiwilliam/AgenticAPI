# LLM Backends

AgenticAPI supports multiple LLM providers through a pluggable `LLMBackend` protocol.

## Built-in Backends

| Backend | Provider | Default Model | Env Variable |
|---|---|---|---|
| `AnthropicBackend` | Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `OpenAIBackend` | OpenAI | `gpt-5.4-mini` | `OPENAI_API_KEY` |
| `GeminiBackend` | Google | `gemini-2.5-flash` | `GOOGLE_API_KEY` |
| `MockBackend` | (Testing) | `mock` | — |

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

## Custom Backend

Any class matching the `LLMBackend` protocol works without inheriting from AgenticAPI:

```python
class MyCustomBackend:
    async def generate(self, prompt: LLMPrompt) -> LLMResponse: ...
    async def generate_stream(self, prompt: LLMPrompt) -> AsyncIterator[LLMChunk]: ...
    @property
    def model_name(self) -> str: ...
```

## MockBackend for Testing

```python
from agenticapi.runtime.llm.mock import MockBackend

backend = MockBackend(responses=["SELECT COUNT(*) FROM orders", "result = 42"])
response = await backend.generate(prompt)
assert response.content == "SELECT COUNT(*) FROM orders"
assert backend.call_count == 1
```
