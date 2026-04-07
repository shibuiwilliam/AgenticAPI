"""AgenticAPI CLI entry point.

Provides the main ``agenticapi`` command with subcommands for
running the development server and displaying version information.
"""

from __future__ import annotations

import argparse
import sys


def cli() -> None:
    """AgenticAPI CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agenticapi",
        description="AgenticAPI — Agent-native web framework with harness engineering",
    )
    subparsers = parser.add_subparsers(dest="command")

    # dev command
    dev_parser = subparsers.add_parser("dev", help="Run development server")
    dev_parser.add_argument(
        "--app",
        required=True,
        help="App import path (e.g. myapp:app)",
    )
    dev_parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    dev_parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    dev_parser.add_argument(
        "--reload",
        action="store_true",
        default=True,
        help="Enable auto-reload (default: True)",
    )

    # console command
    console_parser = subparsers.add_parser("console", help="Run interactive console")
    console_parser.add_argument(
        "--app",
        required=True,
        help="App import path (e.g. myapp:app)",
    )

    # version command
    subparsers.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "dev":
        from agenticapi.cli.dev import run_dev_server

        run_dev_server(
            app_path=args.app,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    elif args.command == "console":
        from agenticapi.cli.console import run_console

        run_console(app_path=args.app)
    elif args.command == "version":
        from agenticapi import __version__

        print(f"AgenticAPI v{__version__}")
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    cli()
