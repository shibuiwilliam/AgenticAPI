"""Development server runner for AgenticAPI.

Wraps uvicorn to provide a convenient development server with
auto-reload support.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def run_dev_server(
    *,
    app_path: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = True,
) -> None:
    """Run the development server using uvicorn.

    Args:
        app_path: ASGI app import path (e.g. "myapp:app").
        host: Bind host address.
        port: Bind port number.
        reload: Whether to enable auto-reload on file changes.
    """
    import uvicorn

    logger.info(
        "dev_server_starting",
        app_path=app_path,
        host=host,
        port=port,
        reload=reload,
    )

    uvicorn.run(
        app_path,
        host=host,
        port=port,
        reload=reload,
    )
