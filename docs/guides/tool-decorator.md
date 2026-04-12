# The `@tool` Decorator

`@tool` is a FastAPI-style decorator that turns a plain Python function into an AgenticAPI `Tool` the LLM can invoke. It auto-generates a JSON Schema from the function's type hints, infers capabilities from the name, and keeps the function fully callable from regular Python.

## The 30-second version

```python
from agenticapi import tool
from agenticapi.runtime.tools import ToolRegistry


@tool(description="Find an order by its numeric id.")
async def get_order(order_id: int, include_lines: bool = True) -> dict:
    row = await db.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
    return {"id": row["id"], "total": row["total"]}


registry = ToolRegistry()
registry.register(get_order)

# The LLM sees this tool as:
# { "name": "get_order",
#   "description": "Find an order by its numeric id.",
#   "parameters": { "type": "object",
#                    "properties": { "order_id": {"type": "integer"},
#                                    "include_lines": {"type": "boolean", "default": true} },
#                    "required": ["order_id"] } }

# You can also call it directly in Python:
order = await get_order(order_id=42)
```

## Why a decorator?

Before `@tool`, writing a tool meant subclassing a protocol, wiring up a `ToolDefinition`, hand-writing a JSON Schema, and implementing an `invoke(**kwargs)` method. That's a lot of boilerplate for something as simple as "call this function."

The decorator collapses all of it:

| Old way | With `@tool` |
|---|---|
| Write a class implementing `Tool` | Write a plain function |
| Write `ToolDefinition(name=..., description=..., parameters_schema=...)` | Write type hints and a docstring |
| Hand-write a JSON Schema | Schema generated from annotations via Pydantic `TypeAdapter` |
| Implement `async def invoke(self, **kwargs)` | The function itself is the invocation |

## Both forms

```python
@tool                          # No args: uses function name, docstring first line as description
async def search_products(query: str) -> list[dict]:
    """Search the product catalog by name or tag."""
    return await db.search(query)


@tool(                         # Explicit overrides
    name="deep_search",
    description="Search products with relevance scoring.",
    capabilities=[ToolCapability.SEARCH],
)
async def _inner_search(query: str, top_k: int = 10) -> list[dict]:
    ...
```

Use the no-arg form when defaults are fine. Switch to the explicit form when you need a name that differs from the Python symbol or want to pin capabilities.

## Sync or async — your choice

```python
@tool
def now() -> str:
    """Return the current timestamp."""
    return datetime.now().isoformat()


@tool
async def fetch_price(symbol: str) -> float:
    """Fetch the latest quote for a ticker symbol."""
    return await exchange.quote(symbol)
```

The framework awaits async functions and calls sync functions directly. Both produce tools with identical metadata.

## JSON Schema generation

Schemas are generated from type annotations using Pydantic's `TypeAdapter`. This means any type Pydantic can validate — primitives, `Optional[T]`, `list[T]`, `dict[str, T]`, Pydantic models, dataclasses, `Literal`, enums — produces an appropriate JSON Schema entry.

```python
from pydantic import BaseModel


class OrderFilter(BaseModel):
    status: Literal["pending", "shipped", "cancelled"] | None = None
    min_total: float = 0.0


@tool
async def search_orders(filter: OrderFilter, limit: int = 20) -> list[dict]:
    """Search orders matching the filter."""
    ...
```

The resulting schema properly describes `filter` as a nested object with the enum constraint on `status`. This is exactly what models expect and it's what enables reliable structured output.

### Return types

The return annotation is captured but not enforced at invocation time — tools return whatever JSON-serializable shape they're written to return. Return annotations are used for documentation and future typed composition.

## Capability inference

If you don't pass `capabilities=[...]`, the decorator inspects the function name and picks defaults:

| Name prefix | Inferred capabilities |
|---|---|
| `get_*`, `read_*`, `list_*`, `find_*`, `fetch_*` | `[READ]` |
| `search_*`, `query_*` | `[SEARCH, READ]` |
| `create_*`, `add_*`, `insert_*` | `[WRITE]` |
| `update_*`, `set_*`, `patch_*` | `[WRITE]` |
| `delete_*`, `remove_*`, `drop_*` | `[WRITE]` |
| `count_*`, `sum_*`, `aggregate_*` | `[AGGREGATE, READ]` |
| `execute_*`, `run_*` | `[EXECUTE]` |

Anything else defaults to `[READ]` and logs a warning at registration time. If the heuristic is wrong, pass `capabilities=[...]` explicitly.

Capabilities drive policy decisions — `DataPolicy` for example can refuse writes based on capability tags.

## Validation at invoke time

When the framework invokes a decorated tool, it validates the kwargs against the generated schema. Bad inputs raise `ToolError` with a precise reason:

```python
@tool
async def get_order(order_id: int) -> dict:
    ...

# LLM returns: {"order_id": "not a number"}
# -> ToolError("get_order: validation failed for parameter 'order_id': input is not a valid integer")
```

This gives the model a structured error it can correct on the next turn, rather than crashing inside your function.

## Registering decorated tools

Decorated functions behave like normal `Tool` instances — you can register them in a `ToolRegistry`, pass them to `AgenticApp(tools=...)`, or mix them with hand-written tools:

```python
from agenticapi import AgenticApp
from agenticapi.runtime.tools import ToolRegistry, DatabaseTool

registry = ToolRegistry()
registry.register(get_order)                          # decorated function
registry.register(search_products)                    # decorated function
registry.register(DatabaseTool(connection=conn))      # class-based tool

app = AgenticApp(title="orders", tools=registry)
```

## Calling decorated tools from Python

A decorated tool is still a regular callable. You can invoke it directly in other handlers, other tools, or test code:

```python
@tool
async def get_order(order_id: int) -> dict:
    ...


async def summarize(order_id: int) -> str:
    order = await get_order(order_id=order_id)     # plain Python call
    return f"Order {order['id']}: ${order['total']:.2f}"
```

This is important for composition — you don't have to route every call through the framework just because it's been decorated.

## Relationship to the class-based `Tool` protocol

`@tool` produces an object that satisfies the same `Tool` protocol as hand-written tools. Everything that works for class-based tools — registries, capability checks, `DataPolicy`, MCP exposure, audit trails — works transparently for decorated tools.

Use `@tool` when you have a plain function. Use a class when you need instance state (connection pools, caches, clients) that shouldn't be re-created per call.

See [API Reference → Tools](../api/tools.md) for the full signature.
