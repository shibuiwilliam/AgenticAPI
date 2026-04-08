# Examples

Ten example applications demonstrate different features and LLM backends.

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

## 07 — Comprehensive (configurable LLM)

DevOps platform combining multiple features per endpoint.

```bash
agenticapi dev --app examples.07_comprehensive.app:app
```

**Demonstrates:** Multi-feature composition per endpoint: pipeline + A2A trust + multi-tool + approval + audit + sessions in each handler.

## 08 — MCP Agent (requires `pip install agenticapi[mcp]`)

Task tracker exposing select endpoints as MCP tools via the Model Context Protocol.

```bash
pip install agenticapi[mcp]
uvicorn examples.08_mcp_agent.app:app --reload
# Test MCP with the inspector:
npx @modelcontextprotocol/inspector http://127.0.0.1:8000/mcp
```

**Demonstrates:** `enable_mcp=True` on endpoint decorators, `MCPCompat`, `expose_as_mcp()`, selective MCP exposure (only query/analytics endpoints, not admin).

## 09 — Auth Agent (no LLM)

API key-protected endpoints with public/protected/admin access levels.

```bash
uvicorn examples.09_auth_agent.app:app --reload
# Public (no auth):
curl -X POST http://127.0.0.1:8000/agent/info.public -H "Content-Type: application/json" -d '{"intent": "hello"}'
# Protected (with API key):
curl -X POST http://127.0.0.1:8000/agent/info.protected -H "Content-Type: application/json" -H "X-API-Key: alice-key-001" -d '{"intent": "details"}'
```

**Demonstrates:** `APIKeyHeader`, `Authenticator`, per-endpoint `auth=`, `AuthUser` in `AgentContext`, role-based access control in handlers.

## 10 — File Handling (no LLM)

File upload, download, and streaming endpoints.

```bash
uvicorn examples.10_file_handling.app:app --reload
# Upload a file:
curl -F 'intent=Analyze this' -F 'document=@README.md' http://127.0.0.1:8000/agent/files.upload
# Download CSV:
curl -X POST http://127.0.0.1:8000/agent/files.export_csv -H "Content-Type: application/json" -d '{"intent": "Export"}' -o export.csv
# Streaming:
curl -X POST http://127.0.0.1:8000/agent/files.stream -H "Content-Type: application/json" -d '{"intent": "Stream logs"}'
```

**Demonstrates:** `UploadedFiles` parameter injection, multipart form parsing, `FileResult` for downloads, `StreamingResponse` passthrough, backward-compatible JSON endpoints.

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
