"""Integration test: FastAPI compatibility layer."""

from __future__ import annotations

from unittest.mock import MagicMock

from agenticapi.app import AgenticApp
from agenticapi.interface.compat.fastapi import mount_fastapi, mount_in_agenticapi


class TestMountFastAPIIntegration:
    def test_mount_agenticapi_in_fastapi(self) -> None:
        """AgenticApp can be mounted into a FastAPI-like app."""
        agenticapi_app = AgenticApp(title="Agent")

        @agenticapi_app.agent_endpoint(name="test")
        async def handler(intent, context):  # type: ignore[no-untyped-def]
            return {"ok": True}

        mock_fastapi = MagicMock()
        mount_fastapi(agenticapi_app, mock_fastapi, path="/agent")

        mock_fastapi.mount.assert_called_once_with("/agent", agenticapi_app)

    def test_mount_sub_app_in_agenticapi(self) -> None:
        """A sub-app can be mounted into AgenticApp."""
        agenticapi_app = AgenticApp(title="Agent")
        sub_app = MagicMock()

        mount_in_agenticapi(agenticapi_app, sub_app, path="/api/v1")

        assert hasattr(agenticapi_app, "_mounted_apps")
        mounted = agenticapi_app._mounted_apps  # type: ignore[attr-defined]
        assert len(mounted) == 1
        assert mounted[0] == ("/api/v1", sub_app)

    def test_mount_multiple_sub_apps(self) -> None:
        """Multiple sub-apps can be mounted."""
        agenticapi_app = AgenticApp(title="Agent")
        sub1 = MagicMock()
        sub2 = MagicMock()

        mount_in_agenticapi(agenticapi_app, sub1, path="/api/v1")
        mount_in_agenticapi(agenticapi_app, sub2, path="/api/v2")

        mounted = agenticapi_app._mounted_apps  # type: ignore[attr-defined]
        assert len(mounted) == 2
