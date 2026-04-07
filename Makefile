.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

.PHONY: install
install: ## Install the package with dev dependencies
	pip install -e ".[dev]"

.PHONY: sync
sync: ## Sync dependencies (uv)
	uv sync --group dev

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

.PHONY: format
format: ## Format code with ruff
	ruff format src/ tests/

.PHONY: lint
lint: ## Run linter
	ruff check src/ tests/

.PHONY: lint-fix
lint-fix: ## Run linter with auto-fix
	ruff check --fix src/ tests/

.PHONY: fix
fix: format lint-fix ## Run all auto-fixable code quality checks

.PHONY: typecheck
typecheck: ## Run mypy type checking
	mypy src/agenticapi/

.PHONY: check
check: ## Run all code quality checks (format, lint, typecheck)
	ruff format --check src/ tests/
	ruff check src/ tests/
	mypy src/agenticapi/

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

.PHONY: test
test: ## Run all tests
	pytest

.PHONY: test-v
test-v: ## Run all tests with verbose output
	pytest -xvs

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	pytest --cov=src/agenticapi --cov-report=term-missing

.PHONY: test-cov-html
test-cov-html: ## Run tests with HTML coverage report
	pytest --cov=src/agenticapi --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

.PHONY: test-unit
test-unit: ## Run unit tests only
	pytest tests/unit/

.PHONY: test-integration
test-integration: ## Run integration tests (no LLM keys required)
	pytest tests/integration/ -m "not requires_llm"

.PHONY: test-e2e
test-e2e: ## Run end-to-end tests
	pytest tests/e2e/

.PHONY: test-benchmark
test-benchmark: ## Run benchmark tests
	pytest tests/benchmarks/ --benchmark-only

# ---------------------------------------------------------------------------
# Full CI pipeline
# ---------------------------------------------------------------------------

.PHONY: ci
ci: check test ## Run the full CI pipeline (lint + typecheck + test)

.PHONY: ci-cov
ci-cov: check test-cov ## Run the full CI pipeline with coverage

# ---------------------------------------------------------------------------
# Development server
# ---------------------------------------------------------------------------

.PHONY: dev
dev: ## Start dev server with hello agent example
	agenticapi dev --app examples.01_hello_agent.app:app

.PHONY: dev-ecommerce
dev-ecommerce: ## Start dev server with ecommerce example
	agenticapi dev --app examples.02_ecommerce.app:app

.PHONY: dev-openai
dev-openai: ## Start dev server with OpenAI example (requires OPENAI_API_KEY)
	agenticapi dev --app examples.03_openai_agent.app:app

.PHONY: console
console: ## Start interactive console with hello agent
	agenticapi console --app examples.01_hello_agent.app:app

# ---------------------------------------------------------------------------
# Build & release
# ---------------------------------------------------------------------------

.PHONY: build
build: ## Build the package
	python -m build

.PHONY: clean
clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
