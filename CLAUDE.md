# CLAUDE.md — AgenticAPI Development Guide

## Project Overview

AgenticAPI is a Python OSS framework that natively integrates coding agents into web applications. Built on Starlette/ASGI, it provides agent endpoints, harness engineering (policy enforcement, sandboxing, approval workflows), and multi-LLM support.

**In a nutshell**: FastAPI is for type-safe REST APIs. AgenticAPI is for harnessed agent APIs.

**Current status**: Phase 1 v0.1.0 complete. ~530 tests, 88% coverage, 75 source files.

---

## Command Reference

### Setup

```bash
uv sync --group dev              # Install all dependencies
uv run agenticapi version        # Verify CLI works
```

### Testing

```bash
uv run pytest                                    # All tests
uv run pytest --ignore=tests/benchmarks -q       # Skip benchmarks (faster)
uv run pytest tests/unit/harness/ -xvs           # Specific directory
uv run pytest --cov=src/agenticapi               # With coverage
uv run pytest tests/benchmarks/                  # Benchmarks only
uv run pytest -m "not requires_llm"              # Skip LLM-dependent tests
```

### Code Quality

```bash
uv run ruff format src/ tests/                   # Format
uv run ruff check src/ tests/                    # Lint
uv run ruff check --fix src/ tests/              # Lint + auto-fix
uv run mypy src/agenticapi/                      # Type check

# Full CI check:
uv run ruff format --check src/ tests/ && uv run ruff check src/ tests/ && uv run mypy src/agenticapi/ && uv run pytest --ignore=tests/benchmarks
```

### Running Examples

```bash
agenticapi dev --app examples.01_hello_agent.app:app          # No LLM needed
agenticapi dev --app examples.06_full_stack.app:app           # Full features
agenticapi console --app examples.02_ecommerce.app:app        # Interactive REPL
```

---

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full architecture document.

### Layer Structure

```
Interface Layer -> Harness Engine -> Agent Runtime -> Sandbox -> Response
```

### Request Flow (simplified)

```
POST /agent/{name} {"intent": "..."} 
  -> IntentParser.parse() -> Intent
  -> IntentScope check
  -> [LLM path]: CodeGenerator -> PolicyEvaluator -> StaticAnalysis -> ApprovalCheck -> ProcessSandbox -> Monitors -> Validators -> AuditRecorder
  -> [Handler path]: handler(intent, context) -> AgentResponse
```

---

## Module Reference

See [docs/modules.md](docs/modules.md) for the complete module reference.

### Key Types

| Type | Location | Purpose |
|---|---|---|
| `AgenticApp` | `app.py` | Main ASGI app (like FastAPI) |
| `AgentRouter` | `routing.py` | Endpoint grouping (like APIRouter) |
| `Intent` | `interface/intent.py` | Parsed user request |
| `AgentResponse` | `interface/response.py` | Agent output with result, reasoning, trace |
| `HarnessEngine` | `harness/engine.py` | Safety pipeline orchestrator |
| `CodePolicy` | `harness/policy/code_policy.py` | Import/eval/exec restrictions |
| `ProcessSandbox` | `harness/sandbox/process.py` | Isolated code execution |
| `LLMBackend` | `runtime/llm/base.py` | Protocol for LLM providers |
| `Tool` | `runtime/tools/base.py` | Protocol for agent tools |

---

## Coding Conventions

### Python

- **Python 3.13+** target. Use `match`, `type` statements, modern type syntax.
- **Type hints on all public APIs.** Internal code: encouraged.
- **Docstrings**: Google style on all public APIs.
- **Format**: `ruff format` (line length 120).
- **Lint**: `ruff check`. **Types**: `mypy --strict`.
- **async-first**: Use `async def` for I/O. Sync for pure computation.

### Data Models

| Use Case | Type | Why |
|---|---|---|
| User-facing config/schema | `pydantic.BaseModel` | Validation, JSON Schema |
| Internal immutable data | `@dataclass(frozen=True, slots=True)` | Lightweight, hashable |
| Internal mutable data | `@dataclass(slots=True)` | Lightweight |
| Enum values | `StrEnum` | String-comparable |
| Pluggable interfaces | `Protocol` | No inheritance dependency |
| Internal inheritance | `ABC` | For SandboxRuntime, OpsAgent |

### Naming

```python
module_name.py          # snake_case
class ClassName:        # PascalCase
async def func_name():  # snake_case
DEFAULT_CONSTANT = 42   # UPPER_SNAKE_CASE
def _private_method():  # _prefix for private
```

### Exceptions

- User-visible errors -> `InterfaceError` (mapped to HTTP 4xx)
- Internal control flow -> `HarnessError` (handled by harness)
- Unexpected errors -> `AgentRuntimeError` (logged, incident-tracked)
- **Never swallow exceptions** (`except Exception: pass` is forbidden)

### Logging

```python
import structlog
logger = structlog.get_logger(__name__)

logger.info("intent_parsed", action=intent.action, confidence=intent.confidence)
logger.warning("policy_near_limit", cpu_usage=0.78, threshold=0.80)
logger.error("execution_failed", error=str(e), trace_id=ctx.trace_id)
```

---

## Security

See [docs/security.md](docs/security.md) for the full security model.

### Defense in Depth (7 layers)

1. **Prompt design** — XML-escaped user input (`html.escape()`)
2. **Static AST analysis** — forbidden imports, eval/exec, getattr, file I/O
3. **Policy evaluation** — CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
4. **Approval workflow** — human-in-the-loop with async lock
5. **Process sandbox** — base64 code transport, subprocess isolation, timeout
6. **Post-execution** — resource monitors, output validators
7. **Audit trail** — bounded ExecutionTrace recording

### Key Security Patterns

- SQL write detection strips comments before keyword check
- Static analysis handles both `eval()` and `builtins.eval()` (attribute access)
- DataPolicy detects backtick-quoted and double-quoted identifiers
- Sandbox namespace pre-populates `data` dict (tools can't be called directly)
- LLM backends have configurable `timeout` parameter

---

## Testing

See [docs/testing.md](docs/testing.md) for the full testing guide.

### Test-First Development

```bash
# 1. Write test
# 2. Verify it fails (red)
# 3. Implement minimum to pass (green)
# 4. Refactor
# 5. ruff format + ruff check + mypy
```

### Performance Targets

| Component | Target |
|---|---|
| IntentParser.parse() (keyword) | < 50ms |
| PolicyEvaluator.evaluate() | < 15ms |
| Static analysis (1000 lines) | < 50ms |
| ProcessSandbox startup | < 100ms |

---

## Examples

See [docs/examples.md](docs/examples.md) for the full examples guide.

| Example | LLM | Features |
|---|---|---|
| `01_hello_agent` | None | Minimal endpoint |
| `02_ecommerce` | None | Routers, policies, approval, tools |
| `03_openai_agent` | OpenAI GPT | Full harness pipeline |
| `04_anthropic_agent` | Anthropic Claude | Policies, ResourcePolicy |
| `05_gemini_agent` | Google Gemini | Sessions, CacheTool |
| `06_full_stack` | Configurable | Everything: pipeline, ops, REST compat, monitors |

---

## How to Extend AgenticAPI

### Adding a New Policy

1. Create `src/agenticapi/harness/policy/my_policy.py` inheriting from `Policy` (in `base.py`)
2. Implement `evaluate(*, code, intent_action, intent_domain, **kwargs) -> PolicyResult`
3. Export from `harness/policy/__init__.py`
4. Export from `harness/__init__.py`
5. Add tests in `tests/unit/harness/test_my_policy.py`
6. Optionally export from `src/agenticapi/__init__.py` if it's a public API

### Adding a New Tool

1. Create `src/agenticapi/runtime/tools/my_tool.py` implementing the `Tool` protocol (in `base.py`)
2. Implement `definition` property returning `ToolDefinition` and `async invoke(**kwargs)` method
3. Export from `runtime/tools/__init__.py`
4. Add tests in `tests/unit/runtime/test_my_tool.py`
5. Reference: `database.py` for the standard pattern

### Adding a New LLM Backend

1. Create `src/agenticapi/runtime/llm/my_backend.py` implementing the `LLMBackend` protocol (in `base.py`)
2. Implement `generate(prompt) -> LLMResponse`, `generate_stream(prompt) -> AsyncIterator[LLMChunk]`, `model_name` property
3. Constructor should accept `api_key`, `model`, `max_tokens`, `timeout` parameters
4. Read API key from env var with explicit parameter override
5. Export from `runtime/llm/__init__.py`
6. Add tests in `tests/unit/runtime/test_my_backend.py`
7. Reference: `anthropic.py`, `openai.py`, `gemini.py` for patterns

### Adding a New Example

1. Create `examples/NN_my_example/app.py` (no `__init__.py` needed)
2. Include docstring with Prerequisites, Run command, and curl test commands
3. Use `TYPE_CHECKING` for `AgentContext` import
4. Use broad `IntentScope` wildcards (`*.read`, `*.analyze`, `*.clarify`) — LLMs may classify domains unpredictably
5. Pass `tools=tools` to `AgenticApp()` if using tools with LLM
6. Update `README.md` Examples section and `docs/examples.md`

---

## Commit Conventions

[Conventional Commits](https://www.conventionalcommits.org/):

```
feat(interface): add IntentParser with LLM-based parsing
fix(harness): fix policy evaluation order
test(sandbox): add benchmark for ProcessSandbox startup
security(sandbox): add AST checks for __import__ patterns
```

Scopes: `interface`, `harness`, `runtime`, `application`, `ops`, `cli`, `testing`, `deps`, `docs`

---

## Phase 2 Roadmap (Not Yet Implemented)

| Feature | Location | Description |
|---|---|---|
| A2A Server/Client | `interface/a2a/server.py`, `client.py` | Inter-agent HTTP communication |
| Service Discovery | `interface/a2a/discovery.py` | Agent registry and lookup |
| AdaptiveDataAccess | `application/data_access.py` | Multi-source data routing |
| BusinessRuleEngine | `application/business_rules.py` | NL-defined business rules |
| CrossDomainOptimizer | `application/cross_domain.py` | Cross-domain optimization |
| LogAnalyst | `ops/log_analyst.py` | Semantic log analysis |
| AutoHealer | `ops/auto_healer.py` | Automated incident recovery |
| PerformanceTuner | `ops/perf_tuner.py` | Runtime optimization |
| IncidentResponder | `ops/incident.py` | Incident management |
| ContainerSandbox | `harness/sandbox/container.py` | Kernel-level isolation |
| GraphQL compat | `interface/compat/graphql.py` | GraphQL schema exposure |
