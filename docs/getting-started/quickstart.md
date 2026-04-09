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

## 5. Programmatic Usage

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

- [Examples](examples.md) — Twelve example apps from hello-world to HTMX
- [Architecture](../guides/architecture.md) — How the layers connect
- [Authentication](../guides/authentication.md) — API key, Bearer, Basic auth
- [File Handling](../guides/file-handling.md) — Upload, download, streaming
- [Harness & Safety](../guides/harness.md) — Policies, sandbox, approval, audit
- [LLM Backends](../guides/llm-backends.md) — Anthropic, OpenAI, Gemini, custom
