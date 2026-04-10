# Examples — agenticapi-claude-agent-sdk

| File | What it shows |
|---|---|
| `01_simple_query.py` | Minimum viable runner — one endpoint, no tools, no policies |
| `02_with_agenticapi_tools.py` | Expose AgenticAPI `Tool` instances to Claude as MCP tools, with `CodePolicy` enforcement and strict tool allow-listing |
| `03_with_audit.py` | Wire the runner to an `AuditRecorder` and expose traces over HTTP |

Each example is a standalone ASGI app you can run with:

```bash
uvicorn examples.01_simple_query:app --reload
```

Set `ANTHROPIC_API_KEY` first.

For full background see the
[Claude Agent SDK extension plan](../../../development/claude_agent_sdk_extension_plan.md).
