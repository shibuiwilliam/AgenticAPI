# Installation

## Requirements

- Python >= 3.13
- pip or uv

## Install from Source

```bash
git clone https://github.com/shibuiwilliam/AgenticAPI.git
cd AgenticAPI
pip install -e ".[dev]"
```

Or with uv:

```bash
uv sync --group dev
```

## Dependencies

AgenticAPI installs the following core dependencies:

| Package | Version | Purpose |
|---|---|---|
| [starlette](https://www.starlette.io/) | >= 1.0 | ASGI foundation |
| [pydantic](https://docs.pydantic.dev/) | >= 2.12 | Validation and schemas |
| [structlog](https://www.structlog.org/) | >= 25.0 | Structured logging |
| [httpx](https://www.python-httpx.org/) | >= 0.28 | Async HTTP client |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | >= 0.89 | Claude API |
| [openai](https://github.com/openai/openai-python) | >= 2.30 | OpenAI API |
| [google-genai](https://github.com/googleapis/python-genai) | >= 1.70 | Gemini API |
| [python-multipart](https://github.com/Kludex/python-multipart) | >= 0.0.20 | File upload parsing |

## Optional Dependencies

```bash
# MCP support (lightweight optional extra)
pip install agenticapi[mcp]

# OpenTelemetry tracing (no-op unless installed)
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp

# Prometheus metrics via OpenTelemetry
pip install opentelemetry-api opentelemetry-sdk prometheus-client
```

The observability layer is designed to degrade gracefully: `configure_tracing()` and `configure_metrics()` silently no-op if these packages aren't installed. See the [Observability guide](../guides/observability.md) for details.

## Extensions

Heavyweight integrations are released as separate packages:

```bash
# Claude Agent SDK (full agentic loop with policies and audit)
pip install agenticapi-claude-agent-sdk
```

See the [Extensions guide](../internals/extensions.md) for the full list and how to build your own.

## Verify Installation

```bash
python -c "import agenticapi; print(agenticapi.__version__)"
```
