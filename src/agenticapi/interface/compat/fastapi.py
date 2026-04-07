"""FastAPI mount compatibility.

Allows mounting AgenticApp within a FastAPI application and vice versa.
Both are ASGI applications, so mounting is straightforward.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agenticapi.app import AgenticApp

logger = structlog.get_logger(__name__)


def mount_fastapi(
    agenticapi_app: AgenticApp,
    fastapi_app: Any,
    *,
    path: str = "/agent",
) -> None:
    """Mount AgenticApp as a sub-application within a FastAPI app.

    Since both AgenticApp and FastAPI are ASGI applications,
    FastAPI's mount() can directly accept AgenticApp.

    Example:
        from fastapi import FastAPI
        from agenticapi import AgenticApp

        fastapi_app = FastAPI()
        agenticapi_app = AgenticApp()

        mount_fastapi(agenticapi_app, fastapi_app, path="/agent")
        # AgenticApp is now accessible at /agent/*

    Args:
        agenticapi_app: The AgenticApp to mount.
        fastapi_app: The FastAPI application to mount into.
        path: The URL path prefix for the AgenticApp.
    """
    fastapi_app.mount(path, agenticapi_app)
    logger.info(
        "agenticapi_mounted_in_fastapi",
        path=path,
        endpoint_count=len(agenticapi_app._endpoints),
    )


def mount_in_agenticapi(
    agenticapi_app: AgenticApp,
    sub_app: Any,
    *,
    path: str = "/api",
) -> None:
    """Mount a FastAPI (or any ASGI) app within AgenticApp.

    Stores the sub-application so it is included when the
    internal Starlette app is built.

    Example:
        from fastapi import FastAPI
        from agenticapi import AgenticApp

        agenticapi_app = AgenticApp()
        fastapi_app = FastAPI()

        mount_in_agenticapi(agenticapi_app, fastapi_app, path="/api")
        # FastAPI is now accessible at /api/*

    Args:
        agenticapi_app: The AgenticApp to mount into.
        sub_app: The ASGI sub-application to mount (e.g., FastAPI).
        path: The URL path prefix for the sub-application.
    """
    if not hasattr(agenticapi_app, "_mounted_apps"):
        agenticapi_app._mounted_apps = []  # type: ignore[attr-defined]
    agenticapi_app._mounted_apps.append((path, sub_app))  # type: ignore[attr-defined]
    # Force Starlette rebuild to include the new mount
    agenticapi_app._starlette_app = None
    logger.info("sub_app_mounted_in_agenticapi", path=path)
