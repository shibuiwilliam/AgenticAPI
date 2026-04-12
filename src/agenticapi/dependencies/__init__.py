"""Dependency injection for AgenticAPI handlers.

The public surface mirrors FastAPI's ``Depends()`` shape so developers
familiar with FastAPI feel immediately at home. AgenticAPI's injector
also handles its built-in injectable types (``Intent``, ``AgentContext``,
``AgentTasks``, ``UploadedFiles``, ``HtmxHeaders``) through the same
machinery, so the previous hard-coded ``if/elif`` chain in
``app.py`` is now driven by a single, extensible scanner.

Example:
    from agenticapi import AgenticApp, Depends, Intent
    from agenticapi.runtime.context import AgentContext

    async def get_db():
        async with engine.connect() as conn:
            yield conn  # teardown after the handler returns

    app = AgenticApp(title="my-service")

    @app.agent_endpoint(name="orders")
    async def list_orders(
        intent: Intent,
        context: AgentContext,
        db = Depends(get_db),
    ):
        return await db.execute(...)
"""

from __future__ import annotations

from agenticapi.dependencies.depends import Dependency, Depends
from agenticapi.dependencies.scanner import (
    InjectionKind,
    InjectionPlan,
    ParamPlan,
    scan_handler,
)
from agenticapi.dependencies.solver import (
    DependencyResolutionError,
    ResolvedHandlerCall,
    invoke_handler,
    solve,
)

__all__ = [
    "Dependency",
    "DependencyResolutionError",
    "Depends",
    "InjectionKind",
    "InjectionPlan",
    "ParamPlan",
    "ResolvedHandlerCall",
    "invoke_handler",
    "scan_handler",
    "solve",
]
