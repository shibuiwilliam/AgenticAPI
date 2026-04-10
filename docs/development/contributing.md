# Contributing

## Development Setup

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
uv sync --group dev    # or: pip install -e ".[dev]"
```

## Running Tests

```bash
make test          # All tests
make test-cov      # With coverage report
make test-unit     # Unit tests only
make test-benchmark  # Performance benchmarks
```

## Code Quality

```bash
make check    # Format check + lint + type check
make fix      # Auto-fix formatting and lint issues
```

Or individually:

```bash
make format      # ruff format
make lint        # ruff check
make typecheck   # mypy strict mode
```

## Full CI Pipeline

```bash
make ci       # lint + typecheck + test
make ci-cov   # lint + typecheck + test with coverage
```

## Dev Server

```bash
make dev              # Hello agent example
make dev-ecommerce    # Ecommerce example
make dev-openai       # OpenAI example
```

## Coding Conventions

- **Python 3.13+** — use `match`, `type` statements, modern syntax
- **Type hints** on all public APIs, internal code where possible
- **Google-style docstrings** on all public APIs
- **`ruff format`** for formatting, **`ruff check`** for linting
- **`mypy` strict mode** for type checking
- **async-first** — `async def` is the default, sync versions get `_sync` suffix
- **Pydantic** for user-facing config, **dataclass** for internal data
- **structlog** for all logging (structured, not string formatting)

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(interface): add IntentParser with LLM-based parsing
fix(harness): fix policy evaluation order
test(sandbox): add benchmark for ProcessSandbox startup
refactor(runtime): extract prompt building into separate module
```

Scopes: `interface`, `harness`, `runtime`, `application`, `ops`, `cli`, `testing`, `deps`, `docs`, `extensions`

## Pre-commit Hooks

Pre-commit hooks run `ruff format`, `ruff check`, and `mypy` automatically before each commit:

```bash
pip install pre-commit
pre-commit install
```

The hook config lives at `.pre-commit-config.yaml`. Hooks check `src/`, `tests/`, and `examples/`.

## Working on Extensions

Extensions live under `extensions/<name>/` as independent packages. To work on an extension:

```bash
cd extensions/agenticapi-claude-agent-sdk
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run mypy src
```

See the [Extensions guide](extensions.md) for the full structure and conventions.

## Building Docs

```bash
pip install mkdocs-material mkdocstrings[python]
mkdocs serve    # Live-reloading at http://127.0.0.1:8001
mkdocs build    # Static site in site/
```
