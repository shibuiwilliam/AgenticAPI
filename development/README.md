# AgenticAPI Developer Documentation

Technical reference documents for AgenticAPI contributors and maintainers. These documents support the [CLAUDE.md](../CLAUDE.md) development guide with detailed specifications.

## Documents

| Document | Description |
|---|---|
| [architecture.md](architecture.md) | Layer structure, module dependencies, request pipeline, FastAPI mapping, constructor signatures |
| [modules.md](modules.md) | Complete source file inventory (80 files, 10,375 lines), exception hierarchy, public API surface |
| [security.md](security.md) | 7-layer defense-in-depth model, authentication schemes, known limitations |
| [testing.md](testing.md) | 666 tests across 55+ files, test patterns, benchmarks, file organization |
| [extending.md](extending.md) | Step-by-step guides for adding policies, tools, LLM backends, examples, auth, MCP, file handling |

## Quick Stats

| Metric | Value |
|---|---|
| Source files | 80 |
| Lines of code | 10,375 |
| Tests | 666 |
| Coverage | 89% |
| Examples | 10 |
| Public API exports | 44 |
| Python version | >= 3.13 |
| Package version | 0.1.0 |

## Related Documentation

- [CLAUDE.md](../CLAUDE.md) — Development guide (commands, conventions, extension points)
- [README.md](../README.md) — User-facing documentation
- [examples/README.md](../examples/README.md) — Example app guide with curl commands
- [docs/](../docs/) — MkDocs site source (served at `/docs` route)
