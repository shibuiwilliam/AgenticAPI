# CI/CD and Code Quality

## GitHub Actions

The CI pipeline is defined in `.github/workflows/ci.yml` and runs on every push and pull request to `main`.

### Jobs

| Job | Runs on | Trigger | Dependencies | What it does |
|---|---|---|---|---|
| `pre-commit` | ubuntu-latest | Push + PR | None | Runs all pre-commit hooks via `pre-commit/action@v3.0.1` |
| `lint` | ubuntu-latest | Push + PR | None | `ruff format --check` + `ruff check` on `src/` and `tests/` |
| `typecheck` | ubuntu-latest | Push + PR | None | `mypy src/agenticapi/` (strict mode) |
| `test` | ubuntu-latest | Push + PR | None | `pytest` (unit + integration), uploads coverage XML artifact |
| `docs` | ubuntu-latest | Push to `main` only | lint, typecheck, test | `mkdocs gh-deploy --force` to GitHub Pages |

### Test Exclusions in CI

The `test` job excludes:
- `tests/benchmarks/` — Performance benchmarks (not deterministic in CI)
- `tests/e2e/` — End-to-end tests (may require LLM API keys or example-specific setup)

### Extensions Are Not Yet Wired into CI

The root workflow tests and type-checks only the core package under `src/`. Extension packages under `extensions/<name>/` have their own tests (offline, stubbed) but are currently run manually:

```bash
uv pip install -e extensions/agenticapi-claude-agent-sdk --no-deps
uv run pytest extensions/agenticapi-claude-agent-sdk/tests
uv run mypy extensions/agenticapi-claude-agent-sdk/src
```

A follow-up will add a matrix `extensions` job that iterates over each extension directory.

### Concurrency

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

Concurrent runs on the same branch are cancelled, keeping only the latest.

### Permissions

- Default: `contents: read` (workflow level)
- `docs` job elevates to: `contents: write`, `pages: write`, `id-token: write`

### Dependency Management

All jobs use:
- `astral-sh/setup-uv@v6` with caching enabled
- `actions/setup-python@v5` with Python 3.13

## Pre-commit Hooks

Configured in `.pre-commit-config.yaml`. Install with:

```bash
uv run pre-commit install         # Install git hooks
uv run pre-commit run --all-files # Run manually on all files
```

### Hook Configuration

| Hook | Repository | Version | What it does |
|---|---|---|---|
| `ruff-format` | `astral-sh/ruff-pre-commit` | v0.15.9 | Checks code formatting on `src/` and `tests/` |
| `ruff` | `astral-sh/ruff-pre-commit` | v0.15.9 | Lints with auto-fix, exits non-zero if fixes applied |
| `mypy` | `pre-commit/mirrors-mypy` | v1.20.0 | Type checks `src/agenticapi/` with all project dependencies |

The mypy hook includes `additional_dependencies` for all core and optional packages so type stubs resolve correctly outside the project virtualenv.

## Makefile Targets

### Setup

| Target | Command | Description |
|---|---|---|
| `make install` | `pip install -e ".[dev]"` | Install with dev dependencies |
| `make sync` | `uv sync --group dev` | Sync dependencies via uv |
| `make pre-commit-install` | `uv run pre-commit install` | Install pre-commit hooks |

### Code Quality

| Target | Command | Description |
|---|---|---|
| `make format` | `ruff format src/ tests/ examples/` | Auto-format code |
| `make lint` | `ruff check src/ tests/ examples/` | Run linter |
| `make lint-fix` | `ruff check --fix src/ tests/ examples/` | Lint with auto-fix |
| `make fix` | `format` + `lint-fix` | All auto-fixable checks |
| `make typecheck` | `mypy src/agenticapi/` | Type checking |
| `make check` | `format --check` + `lint` + `typecheck` | All quality checks (no auto-fix) |

### Testing

| Target | Command | Description |
|---|---|---|
| `make test` | `pytest` | All tests |
| `make test-v` | `pytest -xvs` | Verbose, stop on first failure |
| `make test-cov` | `pytest --cov` | With terminal coverage |
| `make test-cov-html` | `pytest --cov --cov-report=html` | HTML coverage report |
| `make test-unit` | `pytest tests/unit/` | Unit tests only |
| `make test-integration` | `pytest tests/integration/ -m "not requires_llm"` | Integration (no LLM keys) |
| `make test-e2e` | `pytest tests/e2e/` | End-to-end tests |
| `make test-benchmark` | `pytest tests/benchmarks/ --benchmark-only` | Benchmarks only |

### CI Pipeline

| Target | Command | Description |
|---|---|---|
| `make ci` | `check` + `test` | Full CI pipeline |
| `make ci-cov` | `check` + `test-cov` | Full CI with coverage |

### Documentation

| Target | Command | Description |
|---|---|---|
| `make docs` | `mkdocs serve` | Live-reloading local docs |
| `make docs-build` | `mkdocs build` | Build static site |
| `make docs-deploy` | `mkdocs gh-deploy --force` | Deploy to GitHub Pages |

### Other

| Target | Command | Description |
|---|---|---|
| `make dev` | `agenticapi dev --app examples.01_hello_agent.app:app` | Start dev server |
| `make build` | `python -m build` | Build the package |
| `make clean` | Remove build/cache artifacts | Clean up |

## Ruff Configuration

Defined in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 120
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "C4", "SIM", "TCH", "RUF"]
ignore = ["N818"]  # Exception names like PolicyViolation are intentional
```

### Enabled Rule Sets

| Code | Name | What it checks |
|---|---|---|
| E | pycodestyle errors | Basic style errors |
| F | Pyflakes | Unused imports, undefined names |
| W | pycodestyle warnings | Whitespace, line length |
| I | isort | Import sorting |
| N | pep8-naming | Naming conventions |
| UP | pyupgrade | Python version upgrade opportunities |
| B | flake8-bugbear | Common bug patterns |
| A | flake8-builtins | Shadowing builtins |
| C4 | flake8-comprehensions | Comprehension best practices |
| SIM | flake8-simplify | Code simplification |
| TCH | flake8-type-checking | TYPE_CHECKING block usage |
| RUF | Ruff-specific | Ruff's own rules |

## mypy Configuration

```toml
[tool.mypy]
python_version = "3.13"
strict = true
warn_return_any = true
warn_unused_configs = true

[[tool.mypy.overrides]]
module = "mcp.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "agenticapi.interface.compat.mcp"
warn_unused_ignores = false
```

Strict mode enables all optional checks including disallow_untyped_defs, disallow_any_generics, and warn_unreachable. The MCP module overrides are needed because `mcp` is an optional dependency.
