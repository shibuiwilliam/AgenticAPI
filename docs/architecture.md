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
Parse JSON body: {"intent": "...", "session_id": "..."}
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
    |   1. Call handler(intent, context)
    |   2. Wrap result in AgentResponse
    |
    v
Update session with result summary
    |
    v
Return AgentResponse as JSON (HTTP 200, 202, 4xx, 5xx)
```

## Mapping to FastAPI/Starlette

| FastAPI/Starlette | AgenticAPI | Notes |
|---|---|---|
| `FastAPI` | `AgenticApp` | Main ASGI application |
| `@app.get("/path")` | `@app.agent_endpoint(name=...)` | Endpoint registration |
| `APIRouter` | `AgentRouter` | Endpoint grouping with prefix/tags |
| `Request` | `Intent` | Input (natural language -> structured) |
| `Response` | `AgentResponse` | Output with result, reasoning, trace |
| `Depends()` | `HarnessDepends()` | Dependency injection |
| Middleware | `DynamicPipeline` | Dynamic middleware composition |
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
