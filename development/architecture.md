# Architecture

## Layer Structure

```
HTTP Request (ASGI)
  -> Authentication      Scheme extraction + verify function (if auth= configured)
  -> Interface Layer     Intent parsing, session management, response formatting
  -> Harness Engine      Policy evaluation, static analysis, approval workflows
  -> Agent Runtime       LLM code generation, context assembly, tool registry
  -> Sandbox             Isolated process execution with resource limits
  -> Post-Execution      Monitors (resource, output size) + Validators (type, read-only)
  -> Audit               ExecutionTrace recording
  -> Response            Structured result with generated code, reasoning, trace ID
  -> Background Tasks    AgentTasks execute after HTTP response is sent
```

All requests flow top-to-bottom. Each layer is independently testable and dependencies are strictly one-directional.

## Module Dependency Graph

```
agenticapi.interface  -> agenticapi.harness, agenticapi.runtime
agenticapi.harness    -> agenticapi.runtime (interface portion only)
agenticapi.runtime    -> external dependencies only (LLM SDK, httpx, etc.)
agenticapi.application-> agenticapi.runtime, agenticapi.harness
agenticapi.ops        -> agenticapi.runtime, agenticapi.harness, agenticapi.application
agenticapi.security   -> agenticapi.exceptions only
agenticapi.openapi    -> agenticapi.interface.endpoint (for schema generation)
agenticapi.cli        -> all modules
agenticapi.testing    -> all modules
```

**Prohibited dependencies:**
- `runtime` -> `interface` (runtime must not know about the interface)
- `harness` -> `interface` (harness must not know about the interface)
- `harness` -> `application` (harness must not know about the application layer)
- `security` -> `harness` or `runtime` (security is a standalone concern)

## Request Processing Pipeline

```
HTTP POST /agent/{endpoint_name}
    |
    v
Authentication (if auth= configured on endpoint or app)
    |-- Extract credentials via SecurityScheme (APIKeyHeader, HTTPBearer, etc.)
    |-- Call verify function -> AuthUser or AuthenticationError (401)
    |
    v
Parse JSON body: {"intent": "...", "session_id": "...", "context": {...}}
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
    |-- Without LLM: keyword-based classification (English + Japanese)
    |
    v
Check IntentScope.matches(intent) -> PolicyViolation if denied
    |
    v
Build AgentContext (trace_id, endpoint_name, session_id, user_id, auth_user)
    |
    v
Execute intent:
    |
    |-- [LLM + Harness path]:
    |   1. Pre-fetch tool data (call registered tools, sample results)
    |   2. CodeGenerator.generate() -> Python code (data sample in prompt)
    |   3. HarnessEngine.execute():
    |      a. PolicyEvaluator (CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy)
    |      b. Static AST analysis (imports, eval/exec, builtins, file I/O)
    |      c. ApprovalWorkflow check (raise ApprovalRequired if matched)
    |      d. ProcessSandbox.execute() (isolated subprocess, base64 transport, timeout)
    |      e. Post-execution monitors (ResourceMonitor, OutputSizeMonitor)
    |      f. Post-execution validators (OutputTypeValidator, ReadOnlyValidator)
    |      g. AuditRecorder.record() (full ExecutionTrace)
    |   4. Return ExecutionResult -> AgentResponse
    |
    |-- [Direct handler path]:
    |   1. Parse multipart form if present -> inject UploadedFiles
    |   2. Call handler(intent, context [, files] [, tasks])
    |   3. If handler returns FileResult -> file download response
    |   4. If handler returns Starlette Response -> passthrough
    |   5. Otherwise wrap result in AgentResponse
    |
    v
Update session with result summary
    |
    v
Execute AgentTasks (background tasks, after response is sent)
    |
    v
Return response (JSON, file download, or streaming)
    HTTP 200 (success)
    HTTP 202 (approval required)
    HTTP 400 (bad request / parse error)
    HTTP 401 (authentication failed)
    HTTP 403 (policy violation / authorization)
    HTTP 408 (approval timeout)
    HTTP 500 (server error)
    HTTP 502 (tool error)
```

## Auto-Registered Routes

Every `AgenticApp` instance automatically registers:

| Route | Method | Description |
|---|---|---|
| `/agent/{name}` | POST | Agent endpoint (one per registered handler) |
| `/health` | GET | Health check: version, endpoint list, ops agent status |
| `/capabilities` | GET | Structured metadata for all endpoints (for agent discovery) |
| `/openapi.json` | GET | OpenAPI 3.1.0 schema (disable with `openapi_url=None`) |
| `/docs` | GET | Swagger UI (disable with `docs_url=None`) |
| `/redoc` | GET | ReDoc documentation (disable with `redoc_url=None`) |
| `/mcp` | POST | MCP server (only when `expose_as_mcp()` is called) |

## Mapping to FastAPI/Starlette

| FastAPI/Starlette | AgenticAPI | Notes |
|---|---|---|
| `FastAPI()` | `AgenticApp()` | Main ASGI application |
| `@app.get("/path")` | `@app.agent_endpoint(name=...)` | Endpoint registration |
| `APIRouter` | `AgentRouter` | Endpoint grouping with prefix/tags |
| `Request` | `Intent` | Input (natural language -> structured) |
| `Response` | `AgentResponse` | Output with result, reasoning, trace |
| `Depends()` | `HarnessDepends()` | Dependency injection |
| `BackgroundTasks` | `AgentTasks` | Post-response background work |
| `app.add_middleware()` | `app.add_middleware()` | ASGI middleware (CORS, etc.) |
| Middleware stack | + `DynamicPipeline` | Pipeline is for agent-level context enrichment |
| `Security` schemes | `APIKeyHeader`, `HTTPBearer`, etc. | `Authenticator` combines scheme + verify |
| `UploadFile` | `UploadFile` / `UploadedFiles` | Multipart file upload injection |
| `FileResponse` | `FileResult` | File download (bytes, path, or streaming) |
| Pydantic model | Pydantic model | Schema definitions |
| `/docs` | `/docs` | Swagger UI (auto-generated) |
| `/redoc` | `/redoc` | ReDoc (auto-generated) |
| `/openapi.json` | `/openapi.json` | OpenAPI 3.1.0 schema |
| ASGI interface | ASGI interface | Direct uvicorn compatibility |

## AgenticApp Constructor (Complete)

```python
AgenticApp(
    title: str = "AgenticAPI",
    version: str = "0.1.0",
    description: str = "",
    harness: HarnessEngine | None = None,
    llm: LLMBackend | None = None,
    tools: ToolRegistry | None = None,
    middleware: list[Middleware] | None = None,
    auth: Authenticator | None = None,         # App-wide default auth
    docs_url: str | None = "/docs",            # None to disable
    redoc_url: str | None = "/redoc",          # None to disable
    openapi_url: str | None = "/openapi.json", # None to disable all docs
)
```

## HarnessEngine Constructor (Complete)

```python
HarnessEngine(
    policies: list[Policy] | None = None,
    sandbox: ProcessSandbox | None = None,           # Default: auto-created
    audit_recorder: AuditRecorder | None = None,     # Default: auto-created (10k traces)
    approval_workflow: ApprovalWorkflow | None = None,
    monitors: list[ExecutionMonitor] | None = None,  # ResourceMonitor, OutputSizeMonitor
    validators: list[ResultValidator] | None = None,  # OutputTypeValidator, ReadOnlyValidator
)
```

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

## Approval Resolution Flow

```
1. Client sends intent: POST /agent/orders {"intent": "delete cancelled orders"}

2. Server responds HTTP 202:
   {"status": "pending_approval", "approval_request": {"request_id": "abc", "approvers": ["admin"]}}

3. Approver resolves:
   await workflow.resolve("abc", approved=True, approver="admin@example.com")

4. Client retries — now executes.
```

## Capability Discovery

```
GET /capabilities -> {
  "title": "My Service",
  "version": "0.1.0",
  "endpoints": [
    {"name": "orders.query", "description": "...", "autonomy_level": "auto",
     "intent_scope": {"allowed_intents": ["order.*"], "denied_intents": []}}
  ]
}
```
