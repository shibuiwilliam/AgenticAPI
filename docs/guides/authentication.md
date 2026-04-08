# Authentication

AgenticAPI provides HTTP-level authentication following FastAPI's security patterns. Security schemes are callable objects that extract credentials from requests, composed with a verify function via the `Authenticator` class.

## Concepts

Authentication in AgenticAPI is a two-step process:

1. **Security scheme** — extracts raw credentials from the HTTP request (header, query param, etc.)
2. **Verify function** — validates the credentials and returns an `AuthUser` (or `None` if invalid)

These are combined into an `Authenticator` and attached to endpoints via the `auth=` parameter.

```
HTTP Request
  → Security Scheme (extract credentials from headers/params)
  → Verify Function (validate credentials, look up user)
  → AuthUser flows into AgentContext (context.user_id, context.metadata["auth_user"])
  → Handler executes with user info available
```

Auth runs **before body parsing** — invalid credentials are rejected immediately with HTTP 401.

## Quick Example

```python
from agenticapi import AgenticApp
from agenticapi.security import APIKeyHeader, Authenticator, AuthCredentials, AuthUser

# 1. Choose a scheme
api_key = APIKeyHeader(name="X-API-Key")

# 2. Write a verify function
async def verify(credentials: AuthCredentials) -> AuthUser | None:
    KEYS = {"secret-123": ("user-1", "alice"), "admin-456": ("admin-1", "admin")}
    user_data = KEYS.get(credentials.credentials)
    if user_data:
        return AuthUser(user_id=user_data[0], username=user_data[1])
    return None

# 3. Create an Authenticator
auth = Authenticator(scheme=api_key, verify=verify)

# 4. Attach to an endpoint
app = AgenticApp()

@app.agent_endpoint(name="orders", auth=auth)
async def orders(intent, context):
    return {"user": context.user_id}  # "user-1"
```

```bash
# Without auth → 401
curl -X POST http://localhost:8000/agent/orders \
    -H "Content-Type: application/json" \
    -d '{"intent": "show orders"}'

# With auth → 200
curl -X POST http://localhost:8000/agent/orders \
    -H "Content-Type: application/json" \
    -H "X-API-Key: secret-123" \
    -d '{"intent": "show orders"}'
```

## Security Schemes

Four built-in schemes are provided. All implement the `SecurityScheme` protocol.

### APIKeyHeader

Reads an API key from a request header.

```python
from agenticapi.security import APIKeyHeader

scheme = APIKeyHeader(name="X-API-Key")          # default header name
scheme = APIKeyHeader(name="Authorization-Token") # custom header
scheme = APIKeyHeader(auto_error=False)           # return None instead of raising 401
```

### APIKeyQuery

Reads an API key from a query parameter.

```python
from agenticapi.security import APIKeyQuery

scheme = APIKeyQuery(name="api_key")  # ?api_key=secret
```

### HTTPBearer

Reads a Bearer token from the `Authorization` header.

```python
from agenticapi.security import HTTPBearer

scheme = HTTPBearer()
# Expects: Authorization: Bearer <token>
```

### HTTPBasic

Reads Basic credentials from the `Authorization` header.

```python
from agenticapi.security import HTTPBasic

scheme = HTTPBasic()
# Expects: Authorization: Basic <base64(username:password)>
# credentials.credentials will be "username:password"
```

## The `auto_error` Flag

All schemes accept `auto_error` (default `True`):

- **`auto_error=True`** — raises `AuthenticationError` (HTTP 401) when credentials are missing
- **`auto_error=False`** — returns `None`, allowing optional authentication

```python
# Optional auth: some endpoints work without auth but gain features with it
scheme = APIKeyHeader(auto_error=False)
```

## Auth Scopes

### Per-Endpoint Auth

```python
@app.agent_endpoint(name="public")
async def public_handler(intent, context):
    return {"open": True}  # No auth needed

@app.agent_endpoint(name="protected", auth=auth)
async def protected_handler(intent, context):
    return {"user": context.user_id}  # Requires valid credentials
```

### App-Level Auth

Applies to **all** endpoints:

```python
app = AgenticApp(auth=auth)
```

### Router-Level Auth

Applies to all endpoints on that router:

```python
from agenticapi.routing import AgentRouter

router = AgentRouter(prefix="api", auth=auth)

@router.agent_endpoint(name="orders")  # Inherits router auth
async def orders(intent, context): ...

@router.agent_endpoint(name="special", auth=other_auth)  # Overrides router auth
async def special(intent, context): ...
```

### Priority

Endpoint-level `auth=` overrides router-level, which overrides app-level:

```
endpoint auth > router auth > app auth
```

## Accessing the Authenticated User

The `AuthUser` is available in two places:

```python
@app.agent_endpoint(name="me", auth=auth)
async def me(intent, context):
    # Via context.user_id
    print(context.user_id)  # "user-1"

    # Via context.metadata for full AuthUser object
    auth_user = context.metadata["auth_user"]
    print(auth_user.username)  # "alice"
    print(auth_user.roles)    # ("admin",)
    print(auth_user.scopes)   # ()
```

## Role-Based Access Control

Authorization logic (checking roles/permissions) lives in your handler or verify function:

```python
@app.agent_endpoint(name="admin", auth=auth)
async def admin_only(intent, context):
    auth_user = context.metadata.get("auth_user")
    if auth_user and "admin" not in auth_user.roles:
        return {"error": "Admin role required"}
    return {"admin_data": "secret"}
```

## Custom Security Schemes

Implement the `SecurityScheme` protocol to create custom schemes:

```python
from agenticapi.security import AuthCredentials, SecurityScheme
from agenticapi.exceptions import AuthenticationError

class CookieAuth:
    scheme_name = "cookie"
    auto_error = True

    async def __call__(self, request):
        token = request.cookies.get("session_token")
        if token:
            return AuthCredentials(scheme="cookie", credentials=token)
        if self.auto_error:
            raise AuthenticationError("Missing session cookie")
        return None
```

## Data Classes

### AuthCredentials

```python
AuthCredentials(
    scheme="bearer",           # Scheme name
    credentials="jwt-token",   # Raw credential value
    scopes=("read", "write"),  # Optional OAuth2 scopes
)
```

### AuthUser

```python
AuthUser(
    user_id="user-1",                    # Required: unique identifier
    username="alice",                     # Optional: human-readable name
    roles=("admin", "operator"),          # Optional: user roles
    scopes=("read", "write"),            # Optional: OAuth2 scopes
    metadata={"org": "acme"},            # Optional: arbitrary data
)
```

Both are frozen dataclasses — immutable after creation.

## Example

See [`examples/09_auth_agent/`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/09_auth_agent) for a complete working example with public, protected, and admin endpoints.
