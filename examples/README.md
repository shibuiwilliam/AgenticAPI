# AgenticAPI Examples

Thirteen example apps demonstrating AgenticAPI features, from a minimal hello-world to interactive HTMX web apps and a full Claude Agent SDK loop. Each example is a standalone ASGI application that can be run with uvicorn.

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
| [08_mcp_agent](#08-mcp-agent) | Task tracker | No | MCP server: `enable_mcp`, `expose_as_mcp()` |
| [09_auth_agent](#09-auth-agent) | Info service | No | Authentication: `APIKeyHeader`, `Authenticator` |
| [10_file_handling](#10-file-handling) | Files | No | Upload: `UploadedFiles`, download: `FileResult`, streaming |
| [11_html_responses](#11-html-responses) | Pages | No | `HTMLResult`, `PlainTextResult`, `FileResult`, mixed endpoints |
| [12_htmx](#12-htmx) | Todo app | No | `HtmxHeaders`, `htmx_response_headers`, partial updates |
| [13_claude_agent_sdk](#13-claude-agent-sdk) | Assistant + audit | `ANTHROPIC_API_KEY` (optional) | Full Claude Agent SDK loop via `agenticapi-claude-agent-sdk` extension |

## Running Examples

All examples can be started with either uvicorn or the AgenticAPI CLI:

```bash
# Using the CLI
agenticapi dev --app examples.01_hello_agent.app:app

# Using uvicorn directly
uvicorn examples.01_hello_agent.app:app --reload
```

Examples 01, 02, 08-12 require no API keys. Examples 03-05 require a specific LLM provider's API key. Examples 06 and 07 let you choose a provider via `AGENTICAPI_LLM_PROVIDER` and fall back to direct-handler mode when no key is set. Example 08 requires `pip install agenticapi[mcp]`. Example 13 requires `pip install agenticapi-claude-agent-sdk` and (for live calls) `ANTHROPIC_API_KEY` — without them it imports cleanly and the `assistant.audit` endpoint still works.

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

## 08 MCP Agent

A task tracker that exposes select endpoints as [MCP](https://modelcontextprotocol.io) tools, allowing LLM clients (Claude Desktop, Cursor, etc.) to invoke them via the Model Context Protocol. Demonstrates selective MCP exposure — only query and analytics endpoints become tools, while the admin endpoint remains internal.

**Features demonstrated:** `enable_mcp=True` on endpoint decorators, `MCPCompat`, `expose_as_mcp()`, selective MCP exposure, streamable-http transport

**Prerequisites:**

```bash
pip install agenticapi[mcp]
```

```bash
uvicorn examples.08_mcp_agent.app:app --reload
```

```bash
# Native intent API (always available)
curl -X POST http://127.0.0.1:8000/agent/tasks.query \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show all high-priority tasks"}'

curl -X POST http://127.0.0.1:8000/agent/tasks.analytics \
    -H "Content-Type: application/json" \
    -d '{"intent": "What is the completion rate?"}'

# Admin endpoint (NOT exposed via MCP)
curl -X POST http://127.0.0.1:8000/agent/tasks.admin \
    -H "Content-Type: application/json" \
    -d '{"intent": "Reset all task statuses"}'

# Test MCP with the inspector
npx @modelcontextprotocol/inspector http://127.0.0.1:8000/mcp
```

**Endpoints:**
| Endpoint | Description | MCP Tool |
|---|---|---|
| `POST /agent/tasks.query` | Query and filter tasks | Yes |
| `POST /agent/tasks.analytics` | Completion rates, workload | Yes |
| `POST /agent/tasks.admin` | Admin operations | No |

---

## 09 Auth Agent

An information service demonstrating HTTP authentication with API key-protected endpoints. Shows public endpoints alongside protected ones, with role-based access control in handlers.

**Features demonstrated:** `APIKeyHeader` security scheme, `Authenticator` with verify function, per-endpoint `auth=` parameter, `AuthUser` in `AgentContext`, role-based authorization in handlers

```bash
uvicorn examples.09_auth_agent.app:app --reload
```

```bash
# Public endpoint (no auth needed)
curl -X POST http://127.0.0.1:8000/agent/info.public \
    -H "Content-Type: application/json" \
    -d '{"intent": "What services are available?"}'

# Protected endpoint WITHOUT auth (returns 401)
curl -X POST http://127.0.0.1:8000/agent/info.protected \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show user details"}'

# Protected endpoint WITH valid API key
curl -X POST http://127.0.0.1:8000/agent/info.protected \
    -H "Content-Type: application/json" \
    -H "X-API-Key: alice-key-001" \
    -d '{"intent": "Show user details"}'

# Admin endpoint (requires admin role)
curl -X POST http://127.0.0.1:8000/agent/info.admin \
    -H "Content-Type: application/json" \
    -H "X-API-Key: admin-key-999" \
    -d '{"intent": "Show all users"}'
```

**Valid API keys for testing:**
| Key | User | Roles |
|---|---|---|
| `alice-key-001` | alice | operator |
| `bob-key-002` | bob | operator |
| `admin-key-999` | admin | admin, operator |

**Endpoints:**
| Endpoint | Description | Auth |
|---|---|---|
| `POST /agent/info.public` | Public information | None |
| `POST /agent/info.protected` | User information | API key required |
| `POST /agent/info.admin` | Admin operations | API key + admin role |

---

## 10 File Handling

Upload files via multipart form data, download files as binary or streaming responses, and mix file endpoints with standard JSON endpoints in the same app.

**Features demonstrated:** `UploadedFiles` parameter injection, `UploadFile` dataclass, `FileResult` for binary and streaming downloads, Starlette `Response` passthrough, mixed JSON and file endpoints

```bash
uvicorn examples.10_file_handling.app:app --reload
```

```bash
# Upload a file (multipart form)
curl -X POST http://127.0.0.1:8000/agent/files.upload \
    -F 'intent=Analyze this document' \
    -F 'document=@README.md'

# Download a CSV file
curl -X POST http://127.0.0.1:8000/agent/files.export_csv \
    -H "Content-Type: application/json" \
    -d '{"intent": "Export sales data"}' \
    -o export.csv

# Stream a large response
curl -X POST http://127.0.0.1:8000/agent/files.stream \
    -H "Content-Type: application/json" \
    -d '{"intent": "Stream log data"}'

# Normal JSON endpoint (backward compat)
curl -X POST http://127.0.0.1:8000/agent/files.info \
    -H "Content-Type: application/json" \
    -d '{"intent": "What file types are supported?"}'
```

**Endpoints:**
| Endpoint | Description | Response Type |
|---|---|---|
| `POST /agent/files.upload` | Upload files (multipart) | JSON |
| `POST /agent/files.export_csv` | Download CSV file | `text/csv` |
| `POST /agent/files.stream` | Streaming response | `text/plain` (chunked) |
| `POST /agent/files.info` | File info (standard JSON) | JSON |

---

## 11 HTML Responses

Return HTML pages, plain text, and file downloads from agent endpoints using `HTMLResult`, `PlainTextResult`, and `FileResult`. Demonstrates that the same app can serve both JSON APIs and HTML pages.

**Features demonstrated:** `HTMLResult` for HTML responses, `PlainTextResult` for text responses, `FileResult` for HTML file downloads, direct Starlette `Response` passthrough, mixed response types in one app

```bash
uvicorn examples.11_html_responses.app:app --reload
```

```bash
# HTML page
curl -X POST http://127.0.0.1:8000/agent/pages.home \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show the home page"}'

# Dynamic HTML based on intent
curl -X POST http://127.0.0.1:8000/agent/pages.search \
    -H "Content-Type: application/json" \
    -d '{"intent": "Search for Python tutorials"}'

# Plain text status
curl -X POST http://127.0.0.1:8000/agent/pages.status \
    -H "Content-Type: application/json" \
    -d '{"intent": "Check system status"}'

# HTML report download
curl -X POST http://127.0.0.1:8000/agent/pages.report \
    -H "Content-Type: application/json" \
    -d '{"intent": "Generate a report"}' -o report.html

# JSON endpoint (standard AgentResponse)
curl -X POST http://127.0.0.1:8000/agent/pages.api \
    -H "Content-Type: application/json" \
    -d '{"intent": "Get API data"}'
```

**Endpoints:**
| Endpoint | Description | Response Type |
|---|---|---|
| `POST /agent/pages.home` | Static HTML home page | `text/html` |
| `POST /agent/pages.search` | Dynamic HTML search results | `text/html` |
| `POST /agent/pages.status` | Plain text status | `text/plain` |
| `POST /agent/pages.report` | HTML report download | `text/html` (attachment) |
| `POST /agent/pages.api` | Standard JSON API | JSON |

---

## 12 HTMX

An interactive todo-list web app powered by [HTMX](https://htmx.org). Demonstrates how AgenticAPI can serve a full single-page experience with partial page updates — no JavaScript framework needed. The app returns full HTML pages on the first load and HTML fragments on subsequent HTMX requests.

**Features demonstrated:** `HtmxHeaders` parameter injection for detecting HTMX requests, `htmx_response_headers` for controlling client-side swap behavior (`HX-Trigger`, `HX-Reswap`), `HTMLResult` for full pages and fragments, form submission handling, in-memory state

```bash
uvicorn examples.12_htmx.app:app --reload
```

Open `http://127.0.0.1:8000/agent/todo.list` in a browser (send a POST with `{"intent": "Show my todo list"}`) or use curl:

```bash
# Full HTML page (non-HTMX request)
curl -X POST http://127.0.0.1:8000/agent/todo.list \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show my todo list"}'

# HTMX fragment (partial update)
curl -X POST http://127.0.0.1:8000/agent/todo.list \
    -H "Content-Type: application/json" \
    -H "HX-Request: true" \
    -d '{"intent": "Show my todo list"}'

# Add a todo item (returns fragment + HX-Trigger header)
curl -X POST http://127.0.0.1:8000/agent/todo.add \
    -H "Content-Type: application/json" \
    -H "HX-Request: true" \
    -d '{"intent": "Buy groceries"}'

# Search todos (returns filtered fragment)
curl -X POST http://127.0.0.1:8000/agent/todo.search \
    -H "Content-Type: application/json" \
    -H "HX-Request: true" \
    -d '{"intent": "Find tasks about code"}'
```

**Endpoints:**
| Endpoint | Description | Response |
|---|---|---|
| `POST /agent/todo.list` | Full page or todo list fragment | `text/html` |
| `POST /agent/todo.add` | Add a todo, return updated list | `text/html` fragment |
| `POST /agent/todo.search` | Search todos, return filtered list | `text/html` fragment |

---

## 13 Claude Agent SDK

A demo of the **`agenticapi-claude-agent-sdk`** extension, which runs the full Claude Agent SDK loop (planning + tool use + reflection) inside an AgenticAPI endpoint while preserving AgenticAPI's harness guarantees: declarative policies, an audit trail, and a tool registry exposed to the model as MCP tools.

The example wires up a `ClaudeAgentRunner` with a `CodePolicy`, an in-process AgenticAPI tool (`FaqTool`), and an `AuditRecorder`. It also degrades gracefully when the extension or `ANTHROPIC_API_KEY` is missing — the app still imports, the `assistant.audit` endpoint still works, and `assistant.ask` returns a structured error explaining how to install the extension.

**Features demonstrated:** `ClaudeAgentRunner` (the high-level extension entry point), AgenticAPI `Tool` → SDK MCP tool bridge, `CodePolicy` policies bridged into the SDK permission system, `AuditRecorder` capturing every runner session, `autonomy_level="manual"` to delegate execution entirely to the runner, graceful degradation when the extension is missing.

**Prerequisites (optional but recommended):**

```bash
pip install agenticapi-claude-agent-sdk
export ANTHROPIC_API_KEY="sk-ant-..."
```

```bash
uvicorn examples.13_claude_agent_sdk.app:app --reload
```

```bash
# Ask the agent something — full Claude SDK loop, with the FaqTool wired in
curl -X POST http://127.0.0.1:8000/agent/assistant.ask \
    -H "Content-Type: application/json" \
    -d '{"intent": "What is the AgenticAPI harness?"}'

# Inspect the audit trail produced by previous runs
curl -X POST http://127.0.0.1:8000/agent/assistant.audit \
    -H "Content-Type: application/json" \
    -d '{"intent": "Show recent traces"}'

# Health check
curl http://127.0.0.1:8000/health
```

**Endpoints:**
| Endpoint | Description | Autonomy |
|---|---|---|
| `POST /agent/assistant.ask` | Run a full Claude Agent SDK session for the intent | manual |
| `POST /agent/assistant.audit` | Read the in-memory audit trail of past runs | auto |

**`assistant.ask` response shape:**

```json
{
  "status": "completed",
  "result": {
    "answer": "...",
    "ok": true,
    "reasoning": "...",
    "generated_code": null,
    "execution_trace_id": "...",
    "error": null
  }
}
```

When the extension is not installed, `result.ok` is `false`, `result.error` is `"extension_not_installed"`, and `result.message` explains how to install it.

See the extension's own [README](../extensions/agenticapi-claude-agent-sdk/README.md) for the full configuration surface and design notes.

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
