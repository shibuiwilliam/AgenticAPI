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

    # replay command (Phase A6): re-run a historical audit trace
    # through the current pipeline and print a JSON diff.
    replay_parser = subparsers.add_parser(
        "replay",
        help="Replay a historical audit trace through the current pipeline",
    )
    replay_parser.add_argument(
        "trace_id",
        help="Trace id to replay (must exist in the app's audit store)",
    )
    replay_parser.add_argument(
        "--app",
        required=True,
        help="App import path (e.g. myapp:app)",
    )

    # eval command (Phase C6): run a YAML eval set against the app
    # and emit a pass/fail report. Exit code is 0/1/2 so CI can
    # treat a regression as a build failure.
    eval_parser = subparsers.add_parser(
        "eval",
        help="Run an eval set against a live app (regression gate)",
    )
    eval_parser.add_argument(
        "--set",
        dest="eval_set",
        required=True,
        help="Path to the eval set YAML file",
    )
    eval_parser.add_argument(
        "--app",
        required=True,
        help="App import path (e.g. myapp:app)",
    )
    eval_parser.add_argument(
        "--format",
        dest="fmt",
        default="text",
        choices=["text", "json"],
        help="Report output format (default: text)",
    )

    # init command — project scaffolding
    init_parser = subparsers.add_parser("init", help="Generate a new AgenticAPI project")
    init_parser.add_argument("project_name", help="Name of the project to create")
    init_parser.add_argument(
        "--template",
        default="default",
        choices=["default", "chat", "tool-calling"],
        help="Project template (default: default)",
    )

    # bump command — semantic version bumping
    bump_parser = subparsers.add_parser("bump", help="Bump semantic version via git tags")
    bump_parser.add_argument(
        "part",
        choices=["major", "minor", "patch", "prerelease", "current"],
        help="Version part to bump, or 'current' to display",
    )
    bump_parser.add_argument("--dry-run", action="store_true", help="Preview without creating a tag")
    bump_parser.add_argument("--pre-prefix", default="rc", help="Prerelease prefix (default: rc)")
    bump_parser.add_argument("--initial", default="0.1.0", help="Initial version if no tags exist")

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
    elif args.command == "replay":
        from agenticapi.cli.replay import run_replay_cli

        sys.exit(run_replay_cli(trace_id=args.trace_id, app_path=args.app))
    elif args.command == "eval":
        from agenticapi.cli.eval import run_eval_cli

        sys.exit(
            run_eval_cli(
                eval_set_path=args.eval_set,
                app_path=args.app,
                fmt=args.fmt,
            )
        )
    elif args.command == "init":
        from agenticapi.cli.init import run_init

        run_init(project_name=args.project_name, template=args.template)
    elif args.command == "bump":
        from agenticapi.cli.bump import run_bump

        sys.exit(
            run_bump(
                args.part,
                dry_run=args.dry_run,
                pre_prefix=args.pre_prefix,
                initial=args.initial,
            )
        )
    elif args.command == "version":
        from agenticapi import __version__

        print(f"AgenticAPI v{__version__}")
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    cli()
