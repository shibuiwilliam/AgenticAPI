# AgenticAPI Developer Documentation

Technical reference documents for AgenticAPI contributors and maintainers. These documents support the [CLAUDE.md](../CLAUDE.md) development guide with detailed specifications.

## Documents

| Document | Description |
|---|---|
| [architecture.md](architecture.md) | Layer structure, module dependencies, request pipeline, FastAPI mapping, constructor signatures |
| [modules.md](modules.md) | Complete source file inventory (81 files, 10,613 lines), exception hierarchy, public API surface |
| [security.md](security.md) | 7-layer defense-in-depth model, authentication schemes, known limitations |
| [testing.md](testing.md) | 713 tests across 67 files, test patterns, benchmarks, file organization |
| [extending.md](extending.md) | Step-by-step guides for adding policies, tools, LLM backends, examples, auth, MCP, file handling, custom responses, HTMX |
| [ci.md](ci.md) | GitHub Actions CI/CD pipeline, pre-commit hooks, Makefile targets |

## Quick Stats

| Metric | Value |
|---|---|
| Source files | 81 |
| Lines of code | 10,613 |
| Tests | 713 |
| Coverage | 87% |
| Examples | 12 |
| Public API exports | 48 |
| Python version | >= 3.13 |
| Package version | 0.1.0 |

## Related Documentation

- [CLAUDE.md](../CLAUDE.md) — Development guide (commands, conventions, extension points)
- [README.md](../README.md) — User-facing documentation
- [examples/README.md](../examples/README.md) — Example app guide with curl commands
- [docs/](../docs/) — MkDocs site source (served at `/docs` route)
