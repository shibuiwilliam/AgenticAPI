# Contributing to AgenticAPI

Thank you for your interest in contributing to AgenticAPI.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/agenticapi.git
cd agenticapi

# Create a virtual environment and install dependencies
uv sync --group dev

# Verify the setup
uv run pytest
```

## Running Tests

```bash
# All tests (excluding benchmarks)
uv run pytest --ignore=tests/benchmarks

# Specific module
uv run pytest tests/unit/test_app.py

# Specific test
uv run pytest tests/unit/test_app.py::TestAppCreation::test_default_title -xvs

# With coverage
uv run pytest --cov=src/agenticapi --cov-report=term-missing

# Benchmarks
uv run pytest tests/benchmarks/
```

## Code Quality

All code must pass these checks before merging:

```bash
# Format
uv run ruff format src/ tests/

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/agenticapi/

# Full CI check
uv run ruff format --check src/ tests/ && uv run ruff check src/ tests/ && uv run mypy src/agenticapi/ && uv run pytest --ignore=tests/benchmarks
```

## Coding Conventions

- **Python 3.13+** required
- **Async-first**: Use `async def` for I/O operations
- **Type hints**: Required on all public APIs, encouraged on internal code
- **Docstrings**: Google style, required on all public APIs
- **Logging**: Use `structlog` with structured key-value pairs
- **Data models**: Pydantic for user-facing config, frozen dataclasses for internal data
- **Protocols**: Use `Protocol` for pluggable interfaces (LLMBackend, Tool)

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(interface): add IntentParser with LLM-based parsing
fix(harness): fix policy evaluation order for nested policies
test(sandbox): add benchmark for ProcessSandbox startup time
```

Scopes: `interface`, `harness`, `runtime`, `application`, `ops`, `cli`, `testing`, `deps`, `docs`

## Pull Requests

1. Create a feature branch from `main`
2. Write tests first (TDD), then implement
3. Ensure all quality checks pass
4. Write a clear PR description explaining the "why"
5. Request review from a maintainer
