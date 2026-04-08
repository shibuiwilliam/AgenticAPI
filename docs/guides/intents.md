# Intent System

The intent system is the entry point of every AgenticAPI request. It converts natural language into structured `Intent` objects that the rest of the pipeline can reason about.

## Intent Object

Every parsed intent contains:

| Field | Type | Description |
|---|---|---|
| `raw` | `str` | The original natural language request |
| `action` | `IntentAction` | Classified action (READ, WRITE, ANALYZE, EXECUTE, CLARIFY) |
| `domain` | `str` | Business domain (e.g., "order", "product", "user") |
| `parameters` | `dict[str, Any]` | Extracted key-value parameters |
| `confidence` | `float` | Parse confidence (0.0-1.0) |
| `ambiguities` | `list[str]` | Detected ambiguities |
| `session_context` | `dict[str, Any]` | Accumulated session context |

```python
from agenticapi.interface.intent import Intent, IntentAction

intent.action       # IntentAction.READ
intent.domain       # "order"
intent.is_write     # True if WRITE or EXECUTE
intent.needs_clarification  # True if CLARIFY or ambiguities present
```

## IntentParser

The parser has two modes:

### Keyword-Based (Default, No LLM)

```python
from agenticapi.interface.intent import IntentParser

parser = IntentParser()
intent = await parser.parse("Show me recent orders")
# action=READ, domain="order", confidence=0.6
```

The keyword parser recognizes common action words (show, get, create, delete, analyze, etc.) and domain words (order, product, user, etc.) in both English and Japanese.

### LLM-Based (Higher Accuracy)

```python
from agenticapi.runtime.llm import OpenAIBackend

parser = IntentParser(llm=OpenAIBackend())
intent = await parser.parse("Cancel order #1234 and refund the customer")
# action=WRITE, domain="order", parameters={"order_id": "1234"}, confidence=0.95
```

When an LLM is provided, the parser sends a structured prompt asking for JSON output with action, domain, parameters, confidence, and ambiguities. Falls back to keyword parsing if the LLM call fails.

## IntentScope

Constrain which intents an endpoint accepts using wildcard patterns:

```python
from agenticapi import IntentScope

@app.agent_endpoint(
    name="orders",
    intent_scope=IntentScope(
        allowed_intents=["order.*"],         # Allow all order intents
        denied_intents=["order.bulk_delete"], # Deny takes precedence
    ),
)
async def order_agent(intent, context):
    ...
```

Matching uses `fnmatch` against `"{domain}.{action}"`. Denied patterns always take precedence over allowed patterns.
