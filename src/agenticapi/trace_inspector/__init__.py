"""Agent Trace Inspector.

Provides a self-hosted, zero-dependency trace inspection UI at
``/_trace`` with search, diff, cost analytics, conversation viewer,
and compliance export.

Usage::

    app = AgenticApp(trace_url="/_trace")
    # Open http://localhost:8000/_trace in a browser
"""

from __future__ import annotations

from agenticapi.trace_inspector.routes import mount_trace_inspector

__all__ = ["mount_trace_inspector"]
