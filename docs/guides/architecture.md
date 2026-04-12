# Architecture

!!! note
    This page describes the public architecture. For implementation caveats around `BudgetPolicy`, native tool calling, and typed-intent schema enforcement, see [Development -> Current State](../internals/current-state.md).

## Layer Structure

```
HTTP Request (ASGI)
  -> Trace Extraction   W3C traceparent header -> OpenTelemetry Context (if OTel installed)
  -> Authentication     Scheme extraction + verify function (if auth= configured)
  -> Interface Layer    Intent parsing (incl. Intent[T] typed payloads), sessions, response formatting
  -> Dependencies       FastAPI-style Depends() resolution with async teardown
  -> Harness Engine     Policy evaluation, static analysis, approval workflows
  -> Agent Runtime      Tool-first dispatch or LLM code generation, context assembly, tool registry
  -> Sandbox            Isolated process execution with resource limits
  -> Audit              In-memory or SqliteAuditRecorder persistent storage
  -> Observability      OpenTelemetry spans, Prometheus metrics, partial automatic cost attribution
  -> Response           Structured result with generated code, reasoning, trace ID
```

All requests flow top-to-bottom. Each layer is independently testable and dependencies are strictly one-directional.

## Module Dependency Graph

```
agenticapi.dependencies -> (none — standalone injection layer)
agenticapi.interface    -> agenticapi.harness, agenticapi.runtime, agenticapi.dependencies
agenticapi.harness      -> agenticapi.runtime (interface portion only)
agenticapi.runtime      -> external dependencies only (LLM SDK, httpx, etc.)
agenticapi.observability-> optional external (opentelemetry, prometheus), no-op otherwise
agenticapi.application  -> agenticapi.runtime, agenticapi.harness
agenticapi.ops          -> agenticapi.runtime, agenticapi.harness, agenticapi.application
agenticapi.cli          -> all modules
agenticapi.testing      -> all modules
```

**Prohibited dependencies:**
- `runtime` -> `interface` (runtime must not know about the interface)
- `harness` -> `interface` (harness must not know about the interface)
- `harness` -> `application` (harness must not know about the application layer)

## Request Processing Pipeline

```
HTTP POST /agent/{endpoint_name}
    |
    v
Authentication (if auth= configured) -> 401 if invalid
    |
    v
Parse request body:
    |-- JSON: {"intent": "...", "session_id": "..."}
    |-- Multipart: intent form field + file fields -> UploadedFiles
    |
    v
AgenticApp.process_intent()
    |
    v
Resolve endpoint -> AgentEndpointDef
    |
    v
Get or create session -> Session (with TTL-based expiration)
    |
    v
IntentParser.parse() -> Intent (or Intent[T] with validated payload)
    |-- With LLM: structured JSON extraction via prompt; for Intent[T], schema is forwarded
    |-- Without LLM: keyword-based classification
    |
    v
Check IntentScope.matches(intent) -> PolicyViolation if denied
    |
    v
Build AgentContext (trace_id, endpoint_name, session_id, auth_user)
    |
    v
Resolve Depends() tree using the precomputed InjectionPlan (per-request cache, async generators)
    |
    v
Execute intent:
    |
    |-- [LLM + Harness path]:
    |   1. Try tool-first dispatch when tools are registered and the LLM returns exactly one ToolCall
    |   2. Pre-fetch tool data (call registered tools)
    |   3. CodeGenerator.generate() -> Python code (with data sample in prompt)
    |   4. HarnessEngine.execute():
    |      a. PolicyEvaluator.evaluate() (CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy)
    |      b. Static AST analysis (imports, eval/exec, dangerous builtins, file I/O)
    |      c. ApprovalWorkflow check (raise ApprovalRequired if needed)
    |      d. ProcessSandbox.execute() (isolated subprocess with timeout)
    |      e. Post-execution monitors (resource usage, output size)
    |      f. Post-execution validators (JSON serializable, read-only check)
    |      h. AuditRecorder.record() (full ExecutionTrace)
    |   5. Return ExecutionResult -> AgentResponse
    |
    |-- [Direct handler path]:
    |   1. Inject AgentTasks, UploadedFiles, HtmxHeaders, Depends() values as declared
    |   2. Call handler(intent, context, ...)
    |   3. If result is Response/FileResult -> pass through (file download)
    |   4. Otherwise -> wrap result in AgentResponse
    |
    v
Emit observability signals: span events, latency histogram, and any LLM metrics recorded on that path
    |
    v
Execute background tasks (AgentTasks) if any
    |
    v
Update session with result summary
    |
    v
Return response:
    |-- AgentResponse -> JSON (HTTP 200, 202, 4xx, 5xx)
    |-- Response/FileResponse/StreamingResponse -> direct passthrough
```

## Mapping to FastAPI/Starlette

| FastAPI/Starlette | AgenticAPI | Notes |
|---|---|---|
| `FastAPI` | `AgenticApp` | Main ASGI application |
| `@app.get("/path")` | `@app.agent_endpoint(name=...)` | Endpoint registration |
| `APIRouter` | `AgentRouter` | Endpoint grouping with prefix/tags |
| `Request` | `Intent` / `Intent[T]` | Input (natural language -> structured, optionally typed) |
| `Response` | `AgentResponse` | Output with result, reasoning, trace |
| `Depends()` | `Depends()` | FastAPI-compatible dependency injection |
| `BackgroundTasks` | `AgentTasks` | Post-response task execution |
| `UploadFile` | `UploadedFiles` | File upload via multipart |
| `FileResponse` | `FileResult` | File download helper |
| `HTMLResponse` | `HTMLResult` | HTML response |
| `PlainTextResponse` | `PlainTextResult` | Plain text response |
| — | `HtmxHeaders` | HTMX request header detection (auto-injected) |
| Typed request schema | `Intent[T]` | Typed intent payload parsing |
| `@app.get(..., response_model=T)` | `@app.agent_endpoint(..., response_model=T)` | Typed response validation and OpenAPI publication |
| Security schemes | `Authenticator` | API key, Bearer, Basic auth |
| `app.add_middleware()` | `app.add_middleware()` | Starlette middleware (CORS, compression) |
| Middleware stack | + `DynamicPipeline` | DynamicPipeline is for agent context enrichment inside handlers |
| Pydantic model | Pydantic model | Schema definitions |
| OpenTelemetry via middleware | `agenticapi.observability` | Built-in tracing + metrics, no-op if not installed |
| ASGI interface | ASGI interface | Direct uvicorn compatibility |

## Approval Resolution Flow

When a write operation requires human approval, the harness raises `ApprovalRequired` (HTTP 202). The client must resolve the approval before the operation can proceed.

```
1. Client sends intent: POST /agent/orders {"intent": "delete cancelled orders"}

2. Server responds HTTP 202:
   {
     "status": "pending_approval",
     "error": "Approval required by rule 'write_gate'",
     "approval_request": {
       "request_id": "abc123",
       "approvers": ["admin"]
     }
   }

3. Approver resolves (programmatically or via admin UI):
   await workflow.resolve("abc123", approved=True, approver="admin@example.com")

4. Client retries the same intent — now the write action executes.
```

**Key points:**
- `request_id` uniquely identifies the pending approval
- `ApprovalWorkflow.resolve()` is called programmatically (no built-in HTTP endpoint yet)
- After approval, the client must re-submit the original intent
- Approvals expire after `timeout_seconds` (default 3600s)
- Rejected approvals raise `ApprovalDenied` (HTTP 403)
- Expired approvals raise `ApprovalTimeout` (HTTP 408)

## Capability Discovery

External agents can discover what an AgenticAPI service offers:

```
GET /capabilities -> {
  "title": "My Service",
  "version": "0.1.0",
  "endpoints": [
    {
      "name": "orders.query",
      "description": "Query order information",
      "autonomy_level": "auto",
      "intent_scope": {
        "allowed_intents": ["order.*", "*.read"],
        "denied_intents": []
      }
    }
  ]
}
```

This enables agents to programmatically discover endpoints, understand what intents are accepted, and adapt their requests accordingly.

## OpenAPI / Swagger / ReDoc

AgenticApp automatically generates OpenAPI 3.1.0 documentation:

- `GET /openapi.json` — OpenAPI schema
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

Disable with `AgenticApp(docs_url=None, redoc_url=None, openapi_url=None)`.

## MCP (Model Context Protocol) Support

Agent endpoints can be exposed as MCP tools for use by Claude Desktop, Cursor, and other MCP clients. Requires `pip install agentharnessapi[mcp]`.

```python
@app.agent_endpoint(name="search", enable_mcp=True)
async def search(intent, context):
    ...

# Expose MCP-enabled endpoints at /mcp
from agenticapi.interface.compat import expose_as_mcp
expose_as_mcp(app)
```

Test with MCP Inspector: `npx @modelcontextprotocol/inspector http://localhost:8000/mcp`

## Safety Architecture (Defense in Depth)

```
Layer 1: Prompt Design         XML-escaped user input, explicit safety instructions
Layer 2: Static AST Analysis   Forbidden imports, eval/exec, getattr, file I/O
Layer 3: Policy Evaluation     CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
Layer 4: Approval Workflow     Human-in-the-loop for sensitive operations
Layer 5: Process Sandbox       Isolated subprocess, timeout, base64 code transport
Layer 6: Post-Execution        Resource monitors, output validators
Layer 7: Audit Trail           Full ExecutionTrace for every operation
```
