# AgenticAPI Developer Documentation

Technical reference documents for AgenticAPI contributors and maintainers. These documents support the [CLAUDE.md](../CLAUDE.md) development guide with detailed specifications.

## Documents

| Document | Description |
|---|---|
| [architecture.md](architecture.md) | Layer structure, module dependencies, request pipeline, FastAPI mapping, constructor signatures |
| [modules.md](modules.md) | Complete source file inventory (81 files, 10,609 lines), exception hierarchy, public API surface |
| [security.md](security.md) | 7-layer defense-in-depth model, authentication schemes, known limitations |
| [testing.md](testing.md) | 713 tests across 67 files, test patterns, benchmarks, file organization |
| [extending.md](extending.md) | Step-by-step guides for adding policies, tools, LLM backends, examples, auth, MCP, file handling, custom responses, HTMX |
| [extensions.md](extensions.md) | Extensions architecture: separate-package layout, lazy imports, offline testing, publishing |
| [claude_agent_sdk_extension_plan.md](claude_agent_sdk_extension_plan.md) | Design rationale for the `agenticapi-claude-agent-sdk` extension |
| [ci.md](ci.md) | GitHub Actions CI/CD pipeline, pre-commit hooks, Makefile targets |

## Quick Stats

### Core Package (`agenticapi`)

| Metric | Value |
|---|---|
| Source files | 81 |
| Lines of code | 10,609 |
| Tests | 713 |
| Coverage | 87% |
| Examples | 12 |
| Public API exports | 48 |
| Python version | >= 3.13 |
| Package version | 0.1.0 |

### Extensions

| Extension | Version | Source LOC | Tests | Purpose |
|---|---|---|---|---|
| `agenticapi-claude-agent-sdk` | 0.1.0 | 1,610 | 38 | Wraps the Claude Agent SDK for full planning + tool-use loops inside agent endpoints |

## Related Documentation

- [CLAUDE.md](../CLAUDE.md) — Development guide (commands, conventions, extension points)
- [README.md](../README.md) — User-facing documentation
- [examples/README.md](../examples/README.md) — Example app guide with curl commands
- [extensions/](../extensions/) — Extension packages with their own READMEs
- [docs/](../docs/) — MkDocs site source (served at `/docs` route)
