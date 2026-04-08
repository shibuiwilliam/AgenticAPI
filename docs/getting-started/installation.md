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
# MCP support
pip install agenticapi[mcp]
```

## Verify Installation

```bash
python -c "import agenticapi; print(agenticapi.__version__)"
```
