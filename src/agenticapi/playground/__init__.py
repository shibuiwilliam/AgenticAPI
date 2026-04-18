"""Agent Playground & Trace Debugger.

Provides a self-hosted, zero-dependency web UI at ``/_playground``
that lets developers interact with agents, visualise execution
traces, and replay historical runs.

Usage::

    app = AgenticApp(playground_url="/_playground")
    # Open http://localhost:8000/_playground in a browser
"""

from __future__ import annotations

from agenticapi.playground.routes import mount_playground

__all__ = ["mount_playground"]
