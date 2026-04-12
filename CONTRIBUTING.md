# Development - Contributing

First, you might want to see the basic ways to [use AgenticAPI and get started](./docs/getting-started/quickstart.md).

## Developing

### Clone the repository

```bash
$ git clone https://github.com/shibuiwilliam/AgenticAPI.git
$ cd AgenticAPI
```

### Install dependencies

Install all dependencies including dev tools, optional extras, and extensions:

```bash
$ uv sync --all-groups --all-extras
```

Or using Make:

```bash
$ make sync-all
```

This installs AgenticAPI in editable mode, so any changes you make to the source code are reflected immediately -- no reinstall needed.

### Using your local AgenticAPI

After installation you can import your local version directly:

```python
from agenticapi import AgenticApp

app = AgenticApp(title="Dev")
```

If you create a Python file that imports and uses AgenticAPI, run it with:

```bash
$ agenticapi dev --app myapp:app
```

Every time you update the source code, the dev server reloads automatically.

### Format the code

Run the formatter to keep style consistent across the codebase:

```bash
$ uv run ruff format src/ tests/ examples/
```

### Lint

Run the linter and auto-fix what it can:

```bash
$ uv run ruff check --fix src/ tests/ examples/
```

### Type check

Run mypy in strict mode:

```bash
$ uv run mypy src/agenticapi/
```

All public APIs require type annotations.

---

## Tests

Run the full test suite with coverage:

```bash
$ uv run pytest --cov=src/agenticapi --cov-report=html
```

Then open `./htmlcov/index.html` in your browser to explore coverage line by line.

Without coverage (faster):

```bash
$ uv run pytest --ignore=tests/benchmarks
```

Or using Make:

```bash
$ make test
```

### Specific tests

```bash
# One directory
$ uv run pytest tests/unit/harness/ -xvs

# One file
$ uv run pytest tests/unit/test_app.py

# One test
$ uv run pytest tests/unit/test_app.py::TestAppCreation::test_default_title -xvs

# Skip tests that need an LLM API key
$ uv run pytest -m "not requires_llm"

# Benchmarks only
$ uv run pytest tests/benchmarks/
```

### Extension tests

Extensions have their own test suites that run offline (no network, no API keys):

```bash
$ uv run pytest tests/unit/ext/claude_agent_sdk/
```

---

## Docs

### Docs live

During development you can preview the documentation site with live reload:

```bash
$ mkdocs serve -a 127.0.0.1:8001
```

Or:

```bash
$ make docs
```

This serves the docs at <a href="http://127.0.0.1:8001" class="external-link" target="_blank">http://127.0.0.1:8001</a>. Changes to any Markdown file under `docs/` are reflected instantly.

### Docs structure

The documentation source lives under `./docs/` and is built with MkDocs + Material theme:

- **Getting Started** -- installation, quick start, examples tour
- **Guides** -- architecture, typed intents, streaming, safety policies, etc.
- **API Reference** -- auto-generated from Google-style docstrings via `mkdocstrings`
- **Internals** -- module map, extending the framework, implementation notes

Navigation is defined in `mkdocs.yml` > `nav`.

### Docs for tests

The 27 examples in `./examples/` serve double duty: they are runnable apps **and** they are tested end-to-end. Every example has a corresponding test class in `tests/e2e/test_examples.py`.

This means:

- If you add a new example, add an E2E test for it.
- If an example breaks, a test fails -- documentation never silently goes stale.
- You can run an example with `agenticapi dev --app examples.01_hello_agent.app:app` (port 8000) while the docs server runs on port 8001 without conflicts.

---

## Adding new features

Detailed step-by-step recipes for extending every subsystem live in [`CLAUDE.md`](./CLAUDE.md) > "How to Extend AgenticAPI". Here's the short version:

### Adding a new example

1. Create `examples/NN_my_example/app.py` (no `__init__.py` needed).
2. Include a docstring with **Prerequisites**, **Run** command, and **curl** test commands.
3. Add an E2E test class in `tests/e2e/test_examples.py`.
4. Update `examples/README.md`.

### Adding a new policy

1. Create `src/agenticapi/harness/policy/my_policy.py` inheriting from `Policy`.
2. Implement `evaluate()` returning a `PolicyResult`.
3. Export from `harness/policy/__init__.py` and `harness/__init__.py`.
4. Add tests in `tests/unit/harness/`.

### Adding a new LLM backend

1. Create `src/agenticapi/runtime/llm/my_backend.py` implementing the `LLMBackend` protocol.
2. Implement `generate()`, `generate_stream()`, and `model_name`.
3. Parse tool calls into `ToolCall` objects and set `finish_reason`.
4. Add retry via `RetryConfig` for transient provider errors.
5. Export from `runtime/llm/__init__.py` and add tests.

### Adding a new tool

The simplest path -- write a typed `async def` and decorate with `@tool`:

```python
from agenticapi import tool

@tool(description="Look up a user by ID")
async def get_user(user_id: int) -> dict:
    return {"id": user_id, "name": "Alice"}
```

The decorator auto-generates the JSON schema from type hints.

---

## Commit messages

Follow <a href="https://www.conventionalcommits.org/" class="external-link" target="_blank">Conventional Commits</a>:

```
feat(interface): add IntentParser with LLM-based parsing
fix(harness): fix policy evaluation order for nested policies
test(sandbox): add benchmark for ProcessSandbox startup time
docs(guides): add multi-agent orchestration guide
```

Scopes: `interface`, `harness`, `runtime`, `mesh`, `application`, `ops`, `cli`, `testing`, `deps`, `docs`

---

## Pull requests

1. Create a feature branch from `main`: `git checkout -b feat/my-change`
2. Write tests first, then implement.
3. Run the full CI check:

```bash
$ make ci
```

4. Push and open a PR against `main`.
5. Write a clear description explaining **why**, not just what.

### The durability rule

If your PR ships a new increment (new features, not just a bug fix), you must also:

1. Append a new `# Increment N` section to `IMPLEMENTATION_LOG.md`.
2. Move the relevant tasks in `ROADMAP.md` from **Active** into **Shipped**.
3. Refresh the metrics in `ROADMAP.md` > "At a glance".
4. If you added new public API names, update the Key Types table in `CLAUDE.md`.
5. If you added new docs pages, update `mkdocs.yml` > `nav`.

This keeps the roadmap and changelog trustworthy. Without it, status claims drift within one increment.

---

## Automated code and AI

You are welcome to use AI tools (Copilot, Claude, ChatGPT, etc.) to help write code and tests. A few guidelines:

**Put in real effort.** If the human effort you invested -- thinking through the design, writing the prompt, reviewing and editing the output -- is less than the effort a maintainer needs to review the PR, don't submit it.

**Don't submit raw LLM output.** PRs that look like unreviewed copy-paste from a chat session (generic names, unnecessary comments, hallucinated APIs) will be closed.

**Test everything.** AI-generated code must pass the same quality bar as hand-written code: formatting, linting, strict type checking, and the full test suite.

Use the tools wisely and they'll make you faster. Use them carelessly and they'll create work for everyone else.

---

## Where to read more

| Document | What it covers |
|---|---|
| [`README.md`](./README.md) | What the framework is and quick start |
| [`PROJECT.md`](./PROJECT.md) | Stable product vision and architecture pillars |
| [`ROADMAP.md`](./ROADMAP.md) | Execution status: shipped / active / deferred |
| [`CLAUDE.md`](./CLAUDE.md) | Developer guide: commands, conventions, module map, extension recipes |
| [`VISION.md`](./VISION.md) | Forward tracks: Agent Mesh, Hardened Trust, Self-Improving Flywheel |
| [`IMPLEMENTATION_LOG.md`](./IMPLEMENTATION_LOG.md) | Append-only log of shipped increments |
| [`SECURITY.md`](./SECURITY.md) | Vulnerability reporting |
