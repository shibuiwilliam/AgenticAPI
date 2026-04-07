# AgenticAPI Examples

Seven example apps demonstrating AgenticAPI features, from a minimal hello-world to a full-stack multi-feature composition. Each example is a standalone ASGI application that can be run with uvicorn.

Every example automatically serves interactive API docs at `http://127.0.0.1:8000/docs` (Swagger UI) and `http://127.0.0.1:8000/redoc` (ReDoc).

## Overview

| Example | Domain | LLM Required | Key Features |
|---|---|---|---|
| [01_hello_agent](#01-hello-agent) | Greeting | No | Minimal single endpoint |
| [02_ecommerce](#02-ecommerce) | E-commerce | No | Routers, policies, tools, approval |
| [03_openai_agent](#03-openai-agent) | Task tracker | `OPENAI_API_KEY` | OpenAI GPT, harness pipeline |
| [04_anthropic_agent](#04-anthropic-agent) | Product catalogue | `ANTHROPIC_API_KEY` | Claude, ResourcePolicy |
| [05_gemini_agent](#05-gemini-agent) | Support tickets | `GOOGLE_API_KEY` | Gemini, sessions |
| [06_full_stack](#06-full-stack) | Warehouse | Configurable | All features: pipeline, ops, A2A, REST compat |
| [07_comprehensive](#07-comprehensive) | DevOps/Incidents | Configurable | Multi-feature per-endpoint composition |

## Running Examples

All examples can be started with either uvicorn or the AgenticAPI CLI:

```bash
# Using the CLI
agenticapi dev --app examples.01_hello_agent.app:app

# Using uvicorn directly
uvicorn examples.01_hello_agent.app:app --reload
```

Examples 01 and 02 require no API keys. Examples 03-05 require a specific LLM provider's API key. Examples 06 and 07 let you choose a provider via `AGENTICAPI_LLM_PROVIDER` and fall back to direct-handler mode when no key is set.

---

## 01 Hello Agent

The simplest possible AgenticAPI app. A single endpoint that echoes back the user's intent. No LLM, no policies, no tools — just the core decorator pattern.

**Features demonstrated:** `AgenticApp`, `@agent_endpoint`, `Intent`, `AgentResponse`

```bash
agenticapi dev --app examples.01_hello_agent.app:app
```

```bash
curl -X POST http://127.0.0.1:8000/agent/greeter \
    -H "Content-Type: application/json" \
    -d '{"intent": "Hello, how are you?"}'
```

**Endpoints:**
| Endpoint | Description |
|---|---|
| `POST /agent/greeter` | Greets the user |

---

## 02 Ecommerce

A multi-endpoint e-commerce app using routers to organize order and product endpoints. Demonstrates the core building blocks for a real application — without requiring any API keys.

**Features demonstrated:** `AgentRouter` with prefix/tags, `CodePolicy`, `DataPolicy`, `ApprovalWorkflow`, `ApprovalRule`, `DatabaseTool`, `CacheTool`, `ToolRegistry`, `IntentScope`, `process_intent()` programmatic API

```bash
agenticapi dev --app examples.02_ecommerce.app:app
```

```bash
# Query orders
curl -X POST http://127.0.0.1:8000/agent/orders.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show recent orders"}'

# Order analytics
curl -X POST http://127.0.0.1:8000/agent/orders.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Analyze order trends"}'

# Cancel an order (triggers intent scope check)
curl -X POST http://127.0.0.1:8000/agent/orders.update \
    -H "Content-Type: application/json" \
    -d '{"intent": "Cancel order 123"}'

# Search products
curl -X POST http://127.0.0.1:8000/agent/products.search \
    -H "Content-Type: application/json" \
    -d '{"intent": "Search for electronics"}'

# Product analytics
curl -X POST http://127.0.0.1:8000/agent/products.analytics \
    -H "Content-Type: application/json" \
    -d '{"intent": "Which products are low in stock?"}'
```

**Endpoints:**
| Endpoint | Description | Autonomy |
|---|---|---|
| `POST /agent/orders.query` | List, search, count orders | auto |
| `POST /agent/orders.update` | Update/cancel orders | supervised |
| `POST /agent/products.search` | Search products | auto |
| `POST /agent/products.analytics` | Product analytics | auto |

---

## 03 OpenAI Agent

A task tracker powered by OpenAI GPT with the full harness safety pipeline. When `OPENAI_API_KEY` is set, intents are parsed by the LLM and code is generated, evaluated against policies, and executed in a sandbox. Without the key, the app falls back to direct handler invocation.

**Features demonstrated:** `OpenAIBackend`, `HarnessEngine`, `CodePolicy`, `DataPolicy`, `ApprovalWorkflow`, `DatabaseTool`, `CacheTool`, session continuity, full LLM pipeline

**Prerequisites:**

```bash
export OPENAI_API_KEY="sk-..."
```

```bash
agenticapi dev --app examples.03_openai_agent.app:app
```

```bash
# Query tasks
curl -X POST http://127.0.0.1:8000/agent/tasks.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show me all high-priority tasks"}'

# Task analytics
curl -X POST http://127.0.0.1:8000/agent/tasks.analytics \
    -H "Content-Type: application/json" \
    -d '{"intent": "What is the completion rate by assignee?"}'

# Update task (requires approval when LLM is active)
curl -X POST http://127.0.0.1:8000/agent/tasks.update \
    -H "Content-Type: application/json" \
    -d '{"intent": "Update task 1 status to done"}'

# Multi-turn session
curl -X POST http://127.0.0.1:8000/agent/tasks.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show all tasks", "session_id": "sess1"}'

curl -X POST http://127.0.0.1:8000/agent/tasks.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Only the high priority ones", "session_id": "sess1"}'
```

**Endpoints:**
| Endpoint | Description | Autonomy |
|---|---|---|
| `POST /agent/tasks.query` | List and filter tasks | auto |
| `POST /agent/tasks.analytics` | Completion rates, workload | auto |
| `POST /agent/tasks.update` | Update task status | supervised |

---

## 04 Anthropic Agent

A product catalogue agent powered by Anthropic Claude. Demonstrates three policy types including `ResourcePolicy` for CPU/memory limits.

**Features demonstrated:** `AnthropicBackend`, `HarnessEngine`, `CodePolicy`, `DataPolicy`, `ResourcePolicy`, `DatabaseTool`, full LLM pipeline

**Prerequisites:**

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

```bash
agenticapi dev --app examples.04_anthropic_agent.app:app
```

```bash
# Search products
curl -X POST http://127.0.0.1:8000/agent/products.search \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show me all electronics under 50000 yen"}'

# Inventory analysis
curl -X POST http://127.0.0.1:8000/agent/products.inventory \
    -H "Content-Type: application/json" \
    -d '{"intent": "Which products are low in stock?"}'
```

**Endpoints:**
| Endpoint | Description | Autonomy |
|---|---|---|
| `POST /agent/products.search` | Search and filter products | auto |
| `POST /agent/products.inventory` | Stock levels and alerts | auto |

---

## 05 Gemini Agent

A support ticket agent powered by Google Gemini. Demonstrates multi-turn session management for accumulating investigation context across conversation turns.

**Features demonstrated:** `GeminiBackend`, `HarnessEngine`, `CodePolicy`, `DataPolicy`, `DatabaseTool`, `CacheTool`, `SessionManager` (multi-turn), full LLM pipeline

**Prerequisites:**

```bash
export GOOGLE_API_KEY="AIza..."
```

```bash
agenticapi dev --app examples.05_gemini_agent.app:app
```

```bash
# Search tickets
curl -X POST http://127.0.0.1:8000/agent/tickets.search \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show me all open critical tickets"}'

# Support metrics
curl -X POST http://127.0.0.1:8000/agent/tickets.metrics \
    -H "Content-Type: application/json" \
    -d '{"intent": "What is the average resolution time by severity?"}'

# Multi-turn session
curl -X POST http://127.0.0.1:8000/agent/tickets.search \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show billing tickets", "session_id": "sess1"}'

curl -X POST http://127.0.0.1:8000/agent/tickets.search \
    -H "Content-Type: application/json" \
    -d '{"intent": "Which of those are still unresolved?", "session_id": "sess1"}'
```

**Endpoints:**
| Endpoint | Description | Autonomy |
|---|---|---|
| `POST /agent/tickets.search` | Search and filter tickets | auto |
| `POST /agent/tickets.metrics` | Resolution times, workload | auto |

---

## 06 Full Stack

A multi-warehouse inventory management app that exercises every major AgenticAPI feature. Each feature is used in at least one endpoint. The LLM provider is configurable via environment variable.

**Features demonstrated:** `DynamicPipeline` + `PipelineStage`, `OpsAgent` + `OpsHealthStatus`, `CapabilityRegistry` + `TrustScorer` (A2A), `RESTCompat` (REST compatibility), all four policy types (`CodePolicy`, `DataPolicy`, `ResourcePolicy`, `RuntimePolicy`), all four tool types (`DatabaseTool`, `CacheTool`, `HttpClientTool`, `QueueTool`), `ResourceMonitor` + `OutputSizeMonitor`, `OutputTypeValidator` + `ReadOnlyValidator`, `AuditRecorder` + `ConsoleExporter`, `ApprovalWorkflow`, `IntentScope`, `SessionManager`, `process_intent()` API, multiple `AgentRouter` instances

**LLM provider selection:**

```bash
export AGENTICAPI_LLM_PROVIDER=openai     # default — requires OPENAI_API_KEY
export AGENTICAPI_LLM_PROVIDER=anthropic  # requires ANTHROPIC_API_KEY
export AGENTICAPI_LLM_PROVIDER=gemini     # requires GOOGLE_API_KEY
```

If no API key is set, the app runs in direct-handler mode (no code generation).

```bash
agenticapi dev --app examples.06_full_stack.app:app
```

```bash
# Inventory query
curl -X POST http://127.0.0.1:8000/agent/inventory.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show all items in the Tokyo warehouse"}'

# Inventory analytics
curl -X POST http://127.0.0.1:8000/agent/inventory.analytics \
    -H "Content-Type: application/json" \
    -d '{"intent": "Compare stock levels across warehouses"}'

# Shipment tracking
curl -X POST http://127.0.0.1:8000/agent/shipping.track \
    -H "Content-Type: application/json" \
    -d '{"intent": "Where is shipment SHP-001?"}'

# Create shipment (triggers approval workflow when LLM is active)
curl -X POST http://127.0.0.1:8000/agent/shipping.create \
    -H "Content-Type: application/json" \
    -d '{"intent": "Ship 50 units of Laptop from Tokyo to Osaka"}'

# Multi-turn session
curl -X POST http://127.0.0.1:8000/agent/inventory.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show Tokyo warehouse", "session_id": "demo"}'

curl -X POST http://127.0.0.1:8000/agent/inventory.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Which of those are low in stock?", "session_id": "demo"}'

# REST compatibility (same endpoints as GET/POST)
curl "http://127.0.0.1:8000/rest/inventory.query?query=show+all+items"

# Health check (includes ops agent status)
curl http://127.0.0.1:8000/health
```

**Endpoints:**
| Endpoint | Description | Autonomy |
|---|---|---|
| `POST /agent/inventory.query` | Query items across warehouses | auto |
| `POST /agent/inventory.analytics` | Stock comparisons, value analysis | auto |
| `POST /agent/shipping.track` | Track shipment status | auto |
| `POST /agent/shipping.create` | Create shipments (approval required) | supervised |

Also available via REST at `/rest/inventory.query`, `/rest/shipping.track`, etc.

**Programmatic usage:**

```python
import asyncio, importlib
mod = importlib.import_module("examples.06_full_stack.app")
asyncio.run(mod.demo())
```

---

## 07 Comprehensive

A DevOps incident and deployment platform that deliberately combines many features *within each individual endpoint*. While 06_full_stack showcases all features across different endpoints, this example shows how features compose together in realistic per-endpoint scenarios.

**Features demonstrated per endpoint:**

| Endpoint | Pipeline | Tools | A2A | Approval | Audit | Session |
|---|---|---|---|---|---|---|
| `incidents.report` | auth + enrich + cache | DB + Cache + Queue | TrustScorer | Critical incidents | Full trace | Multi-turn triage |
| `incidents.investigate` | auth + rate-limit | DB + HTTP + Cache | CapabilityRegistry + Trust | - | Full trace | Accumulate context |
| `deployments.create` | auth + validate + deps | DB + Queue + HTTP | - | All deploys | Full trace | - |
| `deployments.rollback` | auth + impact | DB + Queue + Cache | TrustScorer | SRE approval | Full trace | - |
| `services.health` | auth | DB + HTTP + Cache | Registry + Trust | - | Full trace | - |

**LLM provider selection:**

```bash
export AGENTICAPI_LLM_PROVIDER=openai     # default
export AGENTICAPI_LLM_PROVIDER=anthropic
export AGENTICAPI_LLM_PROVIDER=gemini
```

```bash
agenticapi dev --app examples.07_comprehensive.app:app
```

```bash
# Report an incident (pipeline + trust + tools + audit + session)
curl -X POST http://127.0.0.1:8000/agent/incidents.report \
    -H "Content-Type: application/json" \
    -d '{"intent": "API gateway returning 502 errors for 15 minutes", "session_id": "inc-001"}'

# Investigate (multi-turn with accumulated context)
curl -X POST http://127.0.0.1:8000/agent/incidents.investigate \
    -H "Content-Type: application/json" \
    -d '{"intent": "Check logs for the payment service", "session_id": "inc-001"}'

# Create deployment (triggers approval workflow)
curl -X POST http://127.0.0.1:8000/agent/deployments.create \
    -H "Content-Type: application/json" \
    -d '{"intent": "Deploy payment-service v2.3.1 to production"}'

# Rollback (pipeline + approval + trust + queue)
curl -X POST http://127.0.0.1:8000/agent/deployments.rollback \
    -H "Content-Type: application/json" \
    -d '{"intent": "Rollback payment-service to v2.3.0"}'

# Service health (ops agent + A2A + tools + pipeline)
curl -X POST http://127.0.0.1:8000/agent/services.health \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show health of all services"}'

# REST compatibility
curl "http://127.0.0.1:8000/rest/services.health?query=show+all+services"

# Health check
curl http://127.0.0.1:8000/health
```

**Endpoints:**
| Endpoint | Description | Autonomy |
|---|---|---|
| `POST /agent/incidents.report` | Report and triage incidents | supervised |
| `POST /agent/incidents.investigate` | Multi-turn investigation | auto |
| `POST /agent/deployments.create` | Create deployments (approval required) | supervised |
| `POST /agent/deployments.rollback` | Rollback deployments (SRE approval) | supervised |
| `POST /agent/services.health` | Service health dashboard | auto |

---

## Common Endpoints

Every example app automatically provides these system endpoints:

| Endpoint | Description |
|---|---|
| `GET /health` | Application health check (includes ops agent status if registered) |
| `GET /capabilities` | Structured metadata about all registered agent endpoints |
| `GET /openapi.json` | OpenAPI 3.1.0 schema |
| `GET /docs` | Swagger UI |
| `GET /redoc` | ReDoc documentation |
