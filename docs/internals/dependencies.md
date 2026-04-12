# Dependency Injection

AgenticAPI provides FastAPI-compatible `Depends()` injection for handler parameters, letting you wire databases, auth, config, and other shared resources without mutating global state.

## Usage

```python
from agenticapi import AgenticApp, Depends, Intent

async def get_db():
    async with engine.connect() as conn:
        yield conn  # cleanup runs after the handler returns

async def get_current_user(db = Depends(get_db)) -> dict:
    return await db.fetch_one("SELECT * FROM users WHERE id = 1")

app = AgenticApp()

@app.agent_endpoint(name="orders")
async def orders(
    intent: Intent,
    context,
    db = Depends(get_db),
    user = Depends(get_current_user),
):
    return {"user": user["name"], "orders": [...]}
```

Supports:
- **Sync and async** providers
- **`yield` providers** with teardown after the handler returns
- **Nested dependencies** (a provider can itself declare `Depends()` params)
- **Caching within a request** — the same dependency is resolved once per request, so multiple handlers in a call graph share the same instance

## Implementation

The dependency system lives in `src/agenticapi/dependencies/` and has three parts:

### `depends.py` — the `Depends()` marker

```python
from agenticapi.dependencies import Depends, Dependency

dep = Depends(get_db)  # returns a Dependency(provider=get_db) instance
```

`Dependency` is a frozen dataclass wrapping the provider callable. `Depends()` is just a thin factory — it exists so the public API mirrors FastAPI's `Depends()` one-to-one.

### `scanner.py` — handler signature scanner

`scan_handler(handler)` inspects a handler's signature and returns an `InjectionPlan` describing, for each parameter:

- `InjectionKind` — which framework-managed value to inject (`INTENT`, `CONTEXT`, `AGENT_TASKS`, `UPLOADED_FILES`, `HTMX_HEADERS`, or `DEPENDENCY` for user-declared `Depends()` params)
- The Pydantic model for typed intent payloads (when `intent: MyPayloadModel` is declared)
- The `Dependency` instance for user-provided providers

Scanning happens **once at registration time**, so hot-path requests don't pay the inspection cost.

### `solver.py` — dependency graph resolver

`ResolvedHandlerCall` is the result of resolving an `InjectionPlan` against a concrete request. The solver:

1. Topologically sorts nested dependencies
2. Calls each provider with its own resolved params
3. Handles sync, async, and `yield`-based providers uniformly
4. Caches resolutions within a single request so diamond-shaped graphs don't double-invoke providers
5. Runs cleanup (post-`yield` code) in reverse order after the handler returns, even on errors

`DependencyResolutionError` is raised if the graph can't be resolved (missing provider, cycle, type mismatch).

## Injection Kinds

Beyond user-declared `Depends()` params, the scanner automatically injects framework values based on type annotations:

| Annotation | Injected value |
|---|---|
| `intent: Intent` | The parsed `Intent` object |
| `intent: Intent[MyPayloadModel]` | Typed intent — LLM output validated against the Pydantic model, available via `intent.payload` |
| `context: AgentContext` | The `AgentContext` for this request |
| `tasks: AgentTasks` | Background-task accumulator |
| `files: UploadedFiles` | Dict of uploaded files (multipart) |
| `htmx: HtmxHeaders` | Parsed HTMX request headers |
| `param = Depends(provider)` | User-provided dependency |

The order of parameters in the handler signature does not matter — the scanner routes each by annotation.

## Caching and Isolation

Dependencies are **request-scoped** by default. Within a single request, two `Depends(get_db)` calls return the same instance. Across requests, each gets a fresh resolution.

There is no global or application-scoped cache — state that outlives a request should be held by a regular module-level object (the harness, the tool registry, etc.) rather than a dependency.

## Errors

| Situation | Exception |
|---|---|
| Provider raises | `DependencyResolutionError` wraps the original |
| `Depends()` used on unsupported param | `DependencyResolutionError` at registration |
| Cycle in dependency graph | `DependencyResolutionError` at scan time |

All `DependencyResolutionError`s inherit from `AgentRuntimeError` and map to **HTTP 500**.
