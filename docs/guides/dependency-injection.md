# Dependency Injection

AgenticAPI handlers support FastAPI-style dependency injection via the `Depends()` marker. Any parameter with a `Depends(...)` default is resolved before the handler runs, and results can be cached per-request for efficiency.

## Why dependency injection?

Handlers commonly need resources like database connections, cache clients, current users, or tenant metadata. Without DI you either build these inline (verbose, hard to test) or stash them on a global (hard to isolate per request). `Depends()` gives you:

- **Composition** — dependencies can themselves depend on other dependencies
- **Generator teardown** — `yield` in a dependency runs cleanup after the response
- **Caching** — same dependency called multiple times in one request runs once
- **Test overrides** — swap a dependency in a test without touching handler code

## Basic usage

```python
from agenticapi import AgenticApp, AgentResponse, Depends, Intent
from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="deps-example")


async def get_db():
    """Open a DB connection for this request, close it after."""
    conn = await connect("postgres://...")
    try:
        yield conn
    finally:
        await conn.close()


async def current_tenant(context: AgentContext) -> str:
    """Extract the tenant id from the auth user."""
    user = context.auth_user
    if user is None:
        raise PermissionError("anonymous requests not allowed")
    return user.metadata.get("tenant_id", "default")


@app.agent_endpoint(name="orders.list")
async def list_orders(
    intent: Intent,
    context: AgentContext,
    db=Depends(get_db),
    tenant: str = Depends(current_tenant),
) -> AgentResponse:
    rows = await db.fetch("SELECT * FROM orders WHERE tenant = $1", tenant)
    return AgentResponse(result={"orders": [dict(r) for r in rows]})
```

When the framework handles a request to `POST /agent/orders.list`:

1. It parses the intent as usual.
2. `get_db()` is called, the generator runs up to `yield`, and the connection is passed in.
3. `current_tenant(context)` is resolved — it receives the already-built `AgentContext`.
4. The handler runs with the resolved kwargs.
5. After the handler returns, `get_db()` resumes past `yield` to close the connection.

## Declaring a dependency

A dependency is any callable — sync or async, function or class — that takes zero or more parameters. Those parameters can themselves be `Depends()` markers, forming a tree.

```python
async def db_pool() -> Pool:
    return await create_pool()


async def get_db(pool: Pool = Depends(db_pool)):
    async with pool.acquire() as conn:
        yield conn


async def current_user(context: AgentContext, db=Depends(get_db)) -> User:
    token = context.auth_user.credentials
    return await db.fetchrow("SELECT * FROM users WHERE token = $1", token)
```

The scanner identifies the dependency graph at **handler registration time** — there is no per-request signature inspection.

## Parameters that are always injected

Some parameters are injected automatically regardless of whether you use `Depends()`:

| Parameter type | Source |
|---|---|
| `Intent` (or `Intent[T]`) | Parsed from the request body |
| `AgentContext` | Built by the framework for the request |
| `AgentTasks` | Accumulator for post-response work |
| `UploadedFiles` | Multipart form data (only if the handler declares it) |
| `HtmxHeaders` | Parsed HTMX request headers |

You do **not** wrap these in `Depends()`. The scanner recognizes them by annotation.

## Caching (`use_cache`)

By default, `Depends()` caches the result per request. Two parameters that call the same dependency get the same object:

```python
@app.agent_endpoint(name="combined")
async def combined(
    intent: Intent,
    context: AgentContext,
    a=Depends(get_db),    # resolved once
    b=Depends(get_db),    # returns the same connection as `a`
) -> dict:
    ...
```

To opt out (e.g., you want two independent connections), pass `use_cache=False`:

```python
a=Depends(get_db, use_cache=False)
b=Depends(get_db, use_cache=False)
```

## Generator teardown

If a dependency uses `yield`, the code after `yield` runs after the handler returns — even if the handler raised. Use this for connection cleanup, transaction rollback, lock release, etc.

```python
async def exclusive_lock(context: AgentContext):
    lock = await acquire_lock(context.trace_id)
    try:
        yield lock
    finally:
        await lock.release()
```

Exceptions from the handler propagate through the teardown; if you want to suppress them, wrap the yield in your own try/except.

## Route-level dependencies

Sometimes you have a dependency that should run for its side effects (e.g., an auth check) but the handler doesn't need its return value. Use the `dependencies=` parameter on `@agent_endpoint`:

```python
async def require_admin(context: AgentContext) -> None:
    if "admin" not in context.auth_user.roles:
        raise AuthorizationError("admin role required")


@app.agent_endpoint(name="orders.purge", dependencies=[Depends(require_admin)])
async def purge(intent: Intent, context: AgentContext) -> dict:
    await db.execute("TRUNCATE orders")
    return {"purged": True}
```

Route-level dependencies run **before** the handler in declared order. If any raises, the handler doesn't run and the error is returned as usual (e.g., `AuthorizationError` → HTTP 403). Route-level deps share the same per-request cache as signature deps, so if both declare the same dependency it's resolved once.

## Test overrides

When writing tests, you can swap a dependency without touching the handler source. The mechanism is deliberately simple: override the dependency function in the cache before calling the handler.

```python
async def fake_db():
    yield FakeConnection()


# in your test
app.dependency_overrides[get_db] = fake_db
response = await app.process_intent("list orders")
app.dependency_overrides.clear()
```

This pattern mirrors FastAPI's `app.dependency_overrides`.

## Error handling

- If a dependency raises, the handler is not called.
- The exception is mapped to an HTTP status the same way handler exceptions are.
- `DependencyResolutionError` indicates a framework-level problem (e.g., a dependency has an unannotated parameter the scanner couldn't satisfy). Treat these as programmer errors — they should surface during registration, not in production requests.

## Relationship to the harness

Dependency injection runs **outside** the harness pipeline. It happens after intent parsing but before either the direct-handler path or the LLM-harness path runs. This means:

- Dependencies are NOT run through the code policy or static analysis — they're your own trusted code.
- LLM-generated code never sees the resolved dependencies directly; those live in the handler's Python frame.
- Budget / audit / approval remain the harness's responsibility.

## Runnable example

See [`examples/14_dependency_injection/app.py`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/14_dependency_injection) — a small bookstore API that exercises every concept above: async generator teardown, nested dependencies, per-request caching, fresh-per-call dependencies, route-level dependencies, the `@tool` decorator, and mixing injectables with `Intent` / `AgentContext` in the same handler signature.

Launch with:

```bash
uvicorn examples.14_dependency_injection.app:app --reload
```

See also [API Reference → Dependency Injection](../api/dependencies.md) for the full `Depends()` signature.
