# Architecture

## Layer Structure

```
HTTP Request (ASGI)
  -> Interface Layer    Intent parsing, session management, response formatting
  -> Harness Engine     Policy evaluation, static analysis, approval workflows
  -> Agent Runtime      LLM code generation, context assembly, tool registry
  -> Sandbox            Isolated process execution with resource limits
  -> Response           Structured result with generated code, reasoning, trace ID
```

All requests flow top-to-bottom. Each layer is independently testable and dependencies are strictly one-directional.

## Module Dependency Graph

```
agenticapi.interface  -> agenticapi.harness, agenticapi.runtime
agenticapi.harness    -> agenticapi.runtime (interface portion only)
agenticapi.runtime    -> external dependencies only (LLM SDK, httpx, etc.)
agenticapi.application-> agenticapi.runtime, agenticapi.harness
agenticapi.ops        -> agenticapi.runtime, agenticapi.harness, agenticapi.application
agenticapi.cli        -> all modules
agenticapi.testing    -> all modules
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
IntentParser.parse() -> Intent
    |-- With LLM: structured JSON extraction via prompt
    |-- Without LLM: keyword-based classification
    |
    v
Check IntentScope.matches(intent) -> PolicyViolation if denied
    |
    v
Build AgentContext (trace_id, endpoint_name, session_id)
    |
    v
Execute intent:
    |
    |-- [LLM + Harness path]:
    |   1. Pre-fetch tool data (call registered tools)
    |   2. CodeGenerator.generate() -> Python code (with data sample in prompt)
    |   3. HarnessEngine.execute():
    |      a. PolicyEvaluator.evaluate() (CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy)
    |      b. Static AST analysis (imports, eval/exec, dangerous builtins, file I/O)
    |      c. ApprovalWorkflow check (raise ApprovalRequired if needed)
    |      d. ProcessSandbox.execute() (isolated subprocess with timeout)
    |      e. Post-execution monitors (resource usage, output size)
    |      f. Post-execution validators (JSON serializable, read-only check)
    |      g. AuditRecorder.record() (full ExecutionTrace)
    |   4. Return ExecutionResult -> AgentResponse
    |
    |-- [Direct handler path]:
    |   1. Inject AgentTasks, UploadedFiles, HtmxHeaders if handler declares them
    |   2. Call handler(intent, context, ...)
    |   3. If result is Response/FileResult -> pass through (file download)
    |   4. Otherwise -> wrap result in AgentResponse
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
| `Request` | `Intent` | Input (natural language -> structured) |
| `Response` | `AgentResponse` | Output with result, reasoning, trace |
| `BackgroundTasks` | `AgentTasks` | Post-response task execution |
| `UploadFile` | `UploadedFiles` | File upload via multipart |
| `FileResponse` | `FileResult` | File download helper |
| `HTMLResponse` | `HTMLResult` | HTML response |
| — | `HtmxHeaders` | HTMX request header detection (auto-injected) |
| Security schemes | `Authenticator` | API key, Bearer, Basic auth |
| `Depends()` | `HarnessDepends()` | Dependency injection |
| `app.add_middleware()` | `app.add_middleware()` | Starlette middleware (CORS, compression) |
| Middleware stack | + `DynamicPipeline` | DynamicPipeline is for agent context enrichment inside handlers |
| Pydantic model | Pydantic model | Schema definitions |
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

Agent endpoints can be exposed as MCP tools for use by Claude Desktop, Cursor, and other MCP clients. Requires `pip install agenticapi[mcp]`.

```python
@app.agent_endpoint(name="search", enable_mcp=True)
async def search(intent, context):
    ...

# Expose MCP-enabled endpoints at /mcp
from agenticapi.interface.compat import expose_as_mcp
app.add_routes(expose_as_mcp(app))
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
