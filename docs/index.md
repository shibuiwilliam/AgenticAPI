# AgenticAPI

**Agent-native web framework with harness engineering for Python.**

AgenticAPI lets you build web applications where endpoints accept natural language intents, dynamically generate code via LLMs, and execute it in a sandboxed, policy-controlled environment. Think of it as **FastAPI for agent-powered APIs** — with safety guardrails built in.

```python
from agenticapi import AgenticApp, AgentResponse, Intent
from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="Hello Agent")

@app.agent_endpoint(name="greeter", autonomy_level="auto")
async def greeter(intent: Intent, context: AgentContext) -> AgentResponse:
    return AgentResponse(
        result={"message": f"Hello! You said: {intent.raw}"},
        reasoning="Direct greeting response",
    )
```

```bash
uvicorn myapp:app --reload
# Swagger UI at http://127.0.0.1:8000/docs
```

## Highlights

- **Intent-based endpoints** — Natural language in, structured results out
- **Dynamic code generation** — LLMs generate Python code on the fly
- **Harness engineering** — Policies, static analysis, sandbox, audit trails
- **Multi-LLM** — Anthropic Claude, OpenAI GPT, Google Gemini, or your own
- **Authentication** — API key, Bearer token, Basic auth — per-endpoint or app-wide
- **Custom responses** — `HTMLResult`, `PlainTextResult`, `FileResult`, or any Starlette `Response`
- **HTMX support** — `HtmxHeaders` auto-injection, partial page updates
- **File handling** — Upload via multipart, download via `FileResult`, streaming
- **MCP support** — Expose endpoints as MCP tools for Claude Desktop, Cursor, etc.
- **OpenAPI / Swagger / ReDoc** — Auto-generated, like FastAPI
- **Background tasks** — Post-response processing via `AgentTasks`
- **Approval workflows** — Human-in-the-loop for sensitive operations
- **ASGI-native** — Built on Starlette, runs on uvicorn

**Current status:** 81 source files, 10,613 lines of code, 713 tests, 88% coverage, 12 examples.

## Quick Links

- [Installation](getting-started/installation.md)
- [Quick Start](getting-started/quickstart.md)
- [Examples](getting-started/examples.md) — 12 runnable apps from hello-world to HTMX
- [Architecture](guides/architecture.md)
- [Authentication](guides/authentication.md)
- [File Handling](guides/file-handling.md)
- [API Reference](api/app.md)
- [GitHub Repository](https://github.com/shibuiwilliam/AgenticAPI)
