# Quick Start

## 1. Simple Handler (No LLM)

The simplest mode — your handler receives a parsed intent and returns a response directly:

```python
from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="My Service")

@app.agent_endpoint(name="orders", autonomy_level="supervised")
async def order_agent(intent: Intent, context: AgentContext) -> AgentResponse:
    return AgentResponse(result={"order_count": 42})
```

Run it:

```bash
uvicorn myapp:app --reload
```

Test it:

```bash
curl -X POST http://127.0.0.1:8000/agent/orders \
    -H "Content-Type: application/json" \
    -d '{"intent": "How many orders do we have?"}'
```

Browse the auto-generated docs at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## 2. With LLM Code Generation and Harness

When you provide an LLM backend and harness engine, AgenticAPI generates code dynamically and executes it safely:

```python
from agenticapi import AgenticApp, CodePolicy, HarnessEngine
from agenticapi.runtime.llm import AnthropicBackend

app = AgenticApp(
    title="Harnessed Agent",
    description="Agent API with safety guardrails",
    llm=AnthropicBackend(model="claude-sonnet-4-6"),
    harness=HarnessEngine(),
)

@app.agent_endpoint(
    name="analytics",
    autonomy_level="supervised",
    policies=[CodePolicy(denied_modules=["os", "subprocess", "sys"])],
)
async def analytics_agent(intent, context):
    pass  # The harness pipeline handles execution
```

The full pipeline: **parse intent** -> **generate code via LLM** -> **evaluate against policies** -> **AST static analysis** -> **execute in sandbox** -> **record audit trace** -> **return response**.

## 3. Using Different LLM Backends

```python
from agenticapi.runtime.llm import AnthropicBackend, OpenAIBackend, GeminiBackend

# Anthropic Claude
llm = AnthropicBackend(model="claude-sonnet-4-6")  # uses ANTHROPIC_API_KEY

# OpenAI GPT
llm = OpenAIBackend(model="gpt-5.4-mini")  # uses OPENAI_API_KEY

# Google Gemini
llm = GeminiBackend(model="gemini-2.5-flash")  # uses GOOGLE_API_KEY
```

All backends implement the same `LLMBackend` protocol with `generate()` and `generate_stream()` methods.

## 4. Multi-Endpoint App with Routers

```python
from agenticapi import AgenticApp, IntentScope
from agenticapi.routing import AgentRouter

orders_router = AgentRouter(prefix="orders", tags=["orders"])
products_router = AgentRouter(prefix="products", tags=["products"])

@orders_router.agent_endpoint(
    name="query",
    description="Query order information",
    intent_scope=IntentScope(allowed_intents=["order.*"]),
    autonomy_level="auto",
)
async def order_query(intent, context):
    return {"orders": [...], "total_count": 42}

@products_router.agent_endpoint(name="search", autonomy_level="auto")
async def product_search(intent, context):
    return {"products": [...]}

app = AgenticApp(title="Ecommerce Agent")
app.include_router(orders_router)
app.include_router(products_router)
```

## 5. Typed Intents with `Intent[T]`

Constrain LLM output to a Pydantic schema by annotating the handler's intent parameter:

```python
from pydantic import BaseModel
from agenticapi import AgenticApp, Intent

class OrderSearch(BaseModel):
    status: str | None = None
    min_total_usd: float = 0.0
    limit: int = 20

@app.agent_endpoint(name="orders.search")
async def search_orders(intent: Intent[OrderSearch], context) -> dict:
    query = intent.payload          # fully typed, already validated
    return {"filter": query.model_dump()}
```

The framework extracts the schema at registration time and validates the resulting payload. `MockBackend` fully exercises provider-side structured output today; the built-in provider backends still need full `response_schema` support. See the [Typed Intents guide](../guides/typed-intents.md).

## 6. Dependency Injection with `Depends()`

Pass resources into handlers via FastAPI-style dependencies:

```python
from agenticapi import Depends

async def get_db():
    conn = await connect_db()
    try:
        yield conn
    finally:
        await conn.close()

@app.agent_endpoint(name="orders.list")
async def list_orders(intent, context, db=Depends(get_db)):
    return {"orders": await db.fetch("SELECT * FROM orders")}
```

Supports generator teardown, caching, nested dependencies, and test overrides. See the [Dependency Injection guide](../guides/dependency-injection.md).

## 7. Tools via `@tool`

Decorate a typed function and register it — schema and capabilities are inferred:

```python
from agenticapi import tool
from agenticapi.runtime.tools import ToolRegistry

@tool(description="Look up a product by SKU")
async def get_product(sku: str) -> dict:
    return await db.get_product(sku)

registry = ToolRegistry()
registry.register(get_product)
```

See the [Tool Decorator guide](../guides/tool-decorator.md).

## 8. Cost Budgeting and Observability

Enforce spend caps and emit OpenTelemetry spans + Prometheus metrics:

```python
from agenticapi import BudgetPolicy, CodePolicy, HarnessEngine, PricingRegistry
from agenticapi.observability import configure_tracing, configure_metrics

configure_tracing(service_name="orders")
configure_metrics(service_name="orders")

budget = BudgetPolicy(
    pricing=PricingRegistry.default(),
    max_per_user_per_day_usd=10.00,
)
harness = HarnessEngine(policies=[budget, CodePolicy()])
app = AgenticApp(title="orders", harness=harness)
```

See the [Cost Budgeting](../guides/cost-budgeting.md) and [Observability](../guides/observability.md) guides for the current explicit-integration pattern.

## 9. Programmatic Usage

You can call the agent pipeline directly without HTTP:

```python
response = await app.process_intent(
    "Show me last month's orders",
    endpoint_name="orders.query",
    session_id="session-123",
)
print(response.result)
print(response.generated_code)
print(response.reasoning)
```

## Next Steps

- [Examples](examples.md) — Twenty example apps from hello-world to streaming release control
- [Architecture](../guides/architecture.md) — How the layers connect
- [Typed Intents](../guides/typed-intents.md) — `Intent[T]` with Pydantic validation
- [Dependency Injection](../guides/dependency-injection.md) — `Depends()` for handlers
- [Cost Budgeting](../guides/cost-budgeting.md) — `BudgetPolicy` and `PricingRegistry`
- [Observability](../guides/observability.md) — OpenTelemetry + Prometheus
- [Authentication](../guides/authentication.md) — API key, Bearer, Basic auth
- [File Handling](../guides/file-handling.md) — Upload, download, streaming
- [Harness & Safety](../guides/harness.md) — Policies, sandbox, approval, audit
- [LLM Backends](../guides/llm-backends.md) — Anthropic, OpenAI, Gemini, custom
- [Extensions](../internals/extensions.md) — Claude Agent SDK and building your own
