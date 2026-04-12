# Typed Intents

`Intent` is generic. Annotate a handler parameter as `Intent[MyPydanticModel]` and the framework will:

1. Extract the Pydantic schema at registration time.
2. Ask the LLM to produce a payload that matches the schema.
3. Validate the LLM's output and hand the handler a fully typed `intent.payload`.

This turns natural-language agents into structured APIs without hand-written parsers.

!!! note
    The typed-intent model is fully implemented in the framework, and `MockBackend` fully exercises structured responses. The built-in Anthropic, OpenAI, and Gemini backends do not yet translate `LLMPrompt.response_schema` into provider-native structured-output APIs, so provider-side schema enforcement is still partial today.

## Motivation

Untyped intents give you `intent.raw` (a string) and `intent.parameters` (an untyped dict). That's fine for demos, but real handlers usually want something like:

- "A user ID, a list of product SKUs, and an optional comment."
- "A date range, a currency, and a grouping dimension."
- "One of three enum values plus an integer between 1 and 100."

Typed intents let you declare that contract once — as a Pydantic model — and have both the LLM and the runtime enforce it.

## Example

```python
from typing import Literal
from pydantic import BaseModel, Field
from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.runtime.context import AgentContext


class OrderSearch(BaseModel):
    """Query parameters for searching orders."""
    status: Literal["pending", "shipped", "cancelled"] | None = None
    min_total_usd: float = Field(default=0.0, ge=0.0)
    customer_email: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


app = AgenticApp(title="orders")


@app.agent_endpoint(name="orders.search")
async def search_orders(
    intent: Intent[OrderSearch],
    context: AgentContext,
) -> AgentResponse:
    query: OrderSearch = intent.payload          # fully typed, fully validated
    rows = await db.search_orders(
        status=query.status,
        min_total=query.min_total_usd,
        email=query.customer_email,
        limit=query.limit,
    )
    return AgentResponse(result={"orders": rows})
```

A request like:

```json
{"intent": "Show me shipped orders over $500 for alice@example.com"}
```

will flow as:

1. `IntentParser` sees that the handler expects `Intent[OrderSearch]`.
2. The parser builds a prompt and forwards `OrderSearch`'s schema via `LLMPrompt.response_schema`.
3. The LLM returns, say, `{"status": "shipped", "min_total_usd": 500.0, "customer_email": "alice@example.com", "limit": 20}`.
4. The framework validates the response against `OrderSearch`; if it fails, validation/fallback logic decides whether to recover or raise `IntentParseError`.
5. The handler runs with `intent.payload` already an `OrderSearch` instance.

## How the schema reaches the parser

The dependency scanner inspects the handler signature at registration time. When it finds an `Intent[T]` annotation, it records the type parameter and forwards its JSON Schema to the `IntentParser` whenever that endpoint is invoked. No runtime signature inspection happens per request.

This means:

- Registration-time errors if `T` isn't a valid Pydantic model (fail fast).
- Zero per-request overhead beyond the LLM call itself.
- The schema is the same one a Pydantic model would produce — you can `.model_json_schema()` on it to see exactly what the LLM is being asked for.

## What counts as a valid `T`?

Any of the following work as the type parameter:

- A Pydantic `BaseModel` subclass
- A dataclass (Pydantic will generate a schema via `TypeAdapter`)
- A `TypedDict`
- Primitive types like `int`, `str`, `list[str]` — rarely useful but supported for completeness

For serious use, always use a Pydantic model. Docstrings on fields become schema descriptions, which the LLM uses to disambiguate.

## Handling validation failures

If the LLM returns JSON that doesn't validate against `T`, the parser raises `IntentParseError`. You can:

- Let it propagate (default — returns HTTP 400 to the client).
- Catch it in a pipeline stage or middleware and retry with a corrective prompt.
- Configure the LLM backend's retry policy so validation errors feed back into a new parse attempt.

## Bare `Intent` still works

`Intent` without a type parameter is still supported — `intent.payload` is then `None` and you read `intent.raw` / `intent.parameters` like before. Typed and untyped endpoints can coexist in the same app.

## Combining with `Depends()`

Typed intents compose naturally with dependency injection:

```python
@app.agent_endpoint(name="orders.create")
async def create_order(
    intent: Intent[NewOrder],
    context: AgentContext,
    db=Depends(get_db),
    user: User = Depends(current_user),
) -> AgentResponse:
    order = await db.insert_order(user_id=user.id, **intent.payload.model_dump())
    return AgentResponse(result={"order_id": order.id})
```

The scanner handles the generic annotation and the dependency markers in the same pass — no extra configuration.

## Best practices

- **Write docstrings on every field.** They become schema descriptions and dramatically improve LLM output quality.
- **Use `Literal` and `Enum` aggressively.** They're the cheapest way to constrain a model.
- **Add validators with `Field(..., ge=..., le=...)`.** They become JSON Schema `minimum`/`maximum`, which the LLM respects.
- **Keep models small.** Deeply nested or huge models make the prompt longer and the output more error-prone. Split them into separate endpoints when possible.
- **Don't reuse one giant model across endpoints.** Each endpoint's model should capture exactly what that endpoint needs.

See [API Reference → Interface](../api/interface.md) for the full `Intent[T]` type.
