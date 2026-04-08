# Types & Exceptions

## Enums

::: agenticapi.types.AutonomyLevel

::: agenticapi.types.Severity

::: agenticapi.types.TraceLevel

## Exception Hierarchy

::: agenticapi.exceptions.AgenticAPIError

### Harness Exceptions

::: agenticapi.exceptions.HarnessError

::: agenticapi.exceptions.PolicyViolation

::: agenticapi.exceptions.SandboxViolation

::: agenticapi.exceptions.ApprovalRequired

::: agenticapi.exceptions.ApprovalDenied

::: agenticapi.exceptions.ApprovalTimeout

### Runtime Exceptions

::: agenticapi.exceptions.AgentRuntimeError

::: agenticapi.exceptions.CodeGenerationError

::: agenticapi.exceptions.CodeExecutionError

::: agenticapi.exceptions.ToolError

::: agenticapi.exceptions.ContextError

### Interface Exceptions

::: agenticapi.exceptions.InterfaceError

::: agenticapi.exceptions.IntentParseError

::: agenticapi.exceptions.SessionError

::: agenticapi.exceptions.A2AError

::: agenticapi.exceptions.AuthenticationError

::: agenticapi.exceptions.AuthorizationError

## HTTP Status Mapping

| Exception | HTTP Status |
|---|---|
| `IntentParseError` | 400 Bad Request |
| `SessionError` | 400 Bad Request |
| `AuthenticationError` | 401 Unauthorized |
| `PolicyViolation` | 403 Forbidden |
| `ApprovalDenied` | 403 Forbidden |
| `SandboxViolation` | 403 Forbidden |
| `AuthorizationError` | 403 Forbidden |
| `ApprovalRequired` | 202 Accepted |
| `ApprovalTimeout` | 408 Request Timeout |
| `CodeGenerationError` | 500 Internal Server Error |
| `CodeExecutionError` | 500 Internal Server Error |
| `ToolError` | 502 Bad Gateway |
| `A2AError` | 502 Bad Gateway |

## Dependency Injection

::: agenticapi.params.HarnessDepends
