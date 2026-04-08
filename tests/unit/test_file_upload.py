"""Tests for file upload support: multipart parsing and UploadedFiles injection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.testclient import TestClient

from agenticapi.app import AgenticApp
from agenticapi.interface.upload import UploadedFiles, UploadFile

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# UploadFile dataclass
# ---------------------------------------------------------------------------


class TestUploadFile:
    def test_construction(self) -> None:
        uf = UploadFile(filename="test.pdf", content_type="application/pdf", content=b"data", size=4)
        assert uf.filename == "test.pdf"
        assert uf.content_type == "application/pdf"
        assert uf.content == b"data"
        assert uf.size == 4


# ---------------------------------------------------------------------------
# Multipart file upload via HTTP
# ---------------------------------------------------------------------------


class TestMultipartUpload:
    def test_upload_file_with_intent(self) -> None:
        """Multipart request with intent field and file field."""
        app = AgenticApp()
        captured: list[dict[str, Any]] = []

        @app.agent_endpoint(name="upload")
        async def upload_handler(intent: Intent, context: AgentContext, files: UploadedFiles) -> dict[str, Any]:
            captured.append({"intent": intent.raw, "files": files})
            if files:
                f = next(iter(files.values()))
                return {"filename": f.filename, "size": f.size}
            return {"filename": None}

        client = TestClient(app)
        response = client.post(
            "/agent/upload",
            data={"intent": "Analyze this document"},
            files={"document": ("report.pdf", b"PDF content here", "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert len(captured) == 1
        assert "document" in captured[0]["files"]
        assert captured[0]["files"]["document"].filename == "report.pdf"
        assert captured[0]["files"]["document"].size == len(b"PDF content here")

    def test_upload_multiple_files(self) -> None:
        """Multiple files in a single multipart request."""
        app = AgenticApp()

        @app.agent_endpoint(name="multi")
        async def multi_handler(intent: Intent, context: AgentContext, files: UploadedFiles) -> dict[str, Any]:
            return {"file_count": len(files), "filenames": sorted(files.keys())}

        client = TestClient(app)
        response = client.post(
            "/agent/multi",
            data={"intent": "Process files"},
            files=[
                ("file1", ("a.txt", b"aaa", "text/plain")),
                ("file2", ("b.txt", b"bbb", "text/plain")),
            ],
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_files_accessible_via_context_metadata(self) -> None:
        """Uploaded files are available in context.metadata['files']."""
        app = AgenticApp()
        captured_ctx: list[AgentContext] = []

        @app.agent_endpoint(name="ctx")
        async def ctx_handler(intent: Intent, context: AgentContext) -> dict[str, Any]:
            captured_ctx.append(context)
            files = context.metadata.get("files", {})
            return {"has_files": bool(files)}

        client = TestClient(app)
        response = client.post(
            "/agent/ctx",
            data={"intent": "Check context"},
            files={"doc": ("test.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 200
        assert len(captured_ctx) == 1
        assert "files" in captured_ctx[0].metadata
        assert "doc" in captured_ctx[0].metadata["files"]

    def test_json_request_still_works(self) -> None:
        """Standard JSON request works when file upload is supported."""
        app = AgenticApp()

        @app.agent_endpoint(name="json")
        async def json_handler(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"message": intent.raw}

        client = TestClient(app)
        response = client.post("/agent/json", json={"intent": "hello world"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_missing_intent_in_multipart_returns_400(self) -> None:
        """Multipart without intent field returns 400."""
        app = AgenticApp()

        @app.agent_endpoint(name="upload")
        async def upload_handler(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {}

        client = TestClient(app)
        response = client.post(
            "/agent/upload",
            data={},  # No intent field
            files={"doc": ("test.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 400

    def test_empty_files_dict_when_no_files_uploaded(self) -> None:
        """UploadedFiles parameter is empty dict when no files in multipart."""
        app = AgenticApp()

        @app.agent_endpoint(name="nofiles")
        async def nofiles_handler(intent: Intent, context: AgentContext, files: UploadedFiles) -> dict[str, int]:
            return {"file_count": len(files)}

        client = TestClient(app)
        # Multipart with only intent, no files
        response = client.post(
            "/agent/nofiles",
            data={"intent": "no files here"},
        )
        assert response.status_code == 200
