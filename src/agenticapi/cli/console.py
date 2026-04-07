"""Interactive REPL console for AgenticAPI.

Provides an interactive shell for sending intents to an AgenticAPI
application and viewing responses in real time.
"""

from __future__ import annotations

import asyncio
import importlib
import sys

import structlog

logger = structlog.get_logger(__name__)


def _load_app(app_path: str):  # type: ignore[no-untyped-def]
    """Import an AgenticApp from a module:attribute path.

    Args:
        app_path: Import path in format "module.path:attribute".

    Returns:
        The AgenticApp instance.

    Raises:
        SystemExit: If the import fails.
    """
    try:
        module_path, attr_name = app_path.split(":")
    except ValueError:
        print(f"Error: Invalid app path '{app_path}'. Expected format: 'module:attribute'")
        sys.exit(1)

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        print(f"Error: Cannot import module '{module_path}': {exc}")
        sys.exit(1)

    app = getattr(module, attr_name, None)
    if app is None:
        print(f"Error: Module '{module_path}' has no attribute '{attr_name}'")
        sys.exit(1)

    return app


def run_console(app_path: str) -> None:
    """Run an interactive console session.

    Loads the specified AgenticAPI application and enters a REPL loop
    where the user can type intents and see agent responses.

    Args:
        app_path: App import path (e.g., "myapp:app").
    """
    app = _load_app(app_path)

    logger.info("console_started", app=app_path, title=getattr(app, "title", ""))

    endpoints = list(getattr(app, "_endpoints", {}).keys())
    print(f"AgenticAPI Console — {getattr(app, 'title', 'App')}")
    print(f"Endpoints: {endpoints}")
    print("Type your intent (or /quit to exit, /endpoints to list endpoints)\n")

    async def _process(raw: str, session_id: str | None) -> dict[str, object]:
        response = await app.process_intent(raw, session_id=session_id)
        from agenticapi.interface.response import ResponseFormatter

        formatter = ResponseFormatter()
        return formatter.format_json(response)

    session_id: str | None = None

    while True:
        try:
            raw = input(">>> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if not raw:
            continue

        if raw == "/quit":
            print("Bye!")
            break
        elif raw == "/endpoints":
            print(f"Endpoints: {endpoints}")
            continue
        elif raw == "/session":
            print(f"Session ID: {session_id}")
            continue
        elif raw.startswith("/session "):
            session_id = raw.split(" ", 1)[1].strip() or None
            print(f"Session ID set to: {session_id}")
            continue

        try:
            result = asyncio.run(_process(raw, session_id))
            _print_response(result)
        except Exception as exc:
            print(f"Error: {exc}\n")


def _print_response(data: dict[str, object]) -> None:
    """Pretty-print an agent response.

    Args:
        data: The formatted response dictionary.
    """
    status = data.get("status", "unknown")
    print(f"\nStatus: {status}")

    if data.get("result") is not None:
        print(f"Result: {data['result']}")

    if data.get("generated_code"):
        print(f"Code: {data['generated_code']}")

    if data.get("reasoning"):
        print(f"Reasoning: {data['reasoning']}")

    if data.get("confidence") is not None:
        print(f"Confidence: {data['confidence']}")

    if data.get("error"):
        print(f"Error: {data['error']}")

    suggestions = data.get("follow_up_suggestions")
    if suggestions:
        print(f"Suggestions: {suggestions}")

    print()
