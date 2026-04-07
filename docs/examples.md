# Examples

Six example applications demonstrate different features and LLM backends.

## 01 — Hello Agent (no LLM)

Minimal single-endpoint agent. No API key needed.

```bash
agenticapi dev --app examples.01_hello_agent.app:app
curl -X POST http://127.0.0.1:8000/agent/greeter \
    -H "Content-Type: application/json" \
    -d '{"intent": "Hello!"}'
```

**Demonstrates:** `AgenticApp`, `@agent_endpoint`, direct handler invocation.

## 02 — Ecommerce (no LLM)

Multi-endpoint app with harness safety features. No API key needed.

```bash
agenticapi dev --app examples.02_ecommerce.app:app
```

**Demonstrates:** `AgentRouter`, `CodePolicy`, `DataPolicy`, `ApprovalWorkflow`, `DatabaseTool`, `CacheTool`.

## 03 — OpenAI Agent (requires `OPENAI_API_KEY`)

Task tracker with LLM code generation and full harness pipeline.

```bash
export OPENAI_API_KEY="sk-..."
agenticapi dev --app examples.03_openai_agent.app:app
```

**Demonstrates:** `OpenAIBackend`, tools, approval workflow, full code generation pipeline.

## 04 — Anthropic Agent (requires `ANTHROPIC_API_KEY`)

Product catalogue with Claude-powered code generation.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
agenticapi dev --app examples.04_anthropic_agent.app:app
```

**Demonstrates:** `AnthropicBackend`, `ResourcePolicy`, `DatabaseTool`.

## 05 — Gemini Agent (requires `GOOGLE_API_KEY`)

Support ticket system with session support for multi-turn conversations.

```bash
export GOOGLE_API_KEY="AIza..."
agenticapi dev --app examples.05_gemini_agent.app:app
```

**Demonstrates:** `GeminiBackend`, `CacheTool`, session management.

## 06 — Full Stack (configurable LLM)

Comprehensive warehouse management system demonstrating every Phase 1 feature.

```bash
export AGENTICAPI_LLM_PROVIDER=openai  # or anthropic, gemini
export OPENAI_API_KEY="sk-..."
agenticapi dev --app examples.06_full_stack.app:app
```

**Demonstrates:** All four policies, approval workflow, DynamicPipeline, OpsAgent, sandbox monitors/validators, audit exporters, REST compatibility, session management, multiple routers, trust scoring.

## Common Patterns

All examples expose:
- `POST /agent/{endpoint_name}` — native intent API
- `GET /health` — health check with version and endpoint list

LLM-powered examples (03-06) run the full pipeline:
```
intent -> LLM code generation -> policy check -> static analysis -> sandbox -> response
```

Non-LLM examples (01-02) invoke handlers directly:
```
intent -> keyword parsing -> handler function -> response
```
