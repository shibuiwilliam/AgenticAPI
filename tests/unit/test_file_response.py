"""Tests for file download support: FileResult and Response passthrough."""

from __future__ import annotations

import tempfile
from typing import TYPE_CHECKING

from starlette.responses import FileResponse, Response, StreamingResponse
from starlette.testclient import TestClient

from agenticapi.app import AgenticApp
from agenticapi.interface.response import FileResult

if TYPE_CHECKING:
    from agenticapi.interface.intent import Intent
    from agenticapi.runtime.context import AgentContext


# ---------------------------------------------------------------------------
# FileResult.to_response()
# ---------------------------------------------------------------------------


class TestFileResultToResponse:
    def test_bytes_content_produces_response(self) -> None:
        fr = FileResult(content=b"hello world", media_type="text/plain")
        resp = fr.to_response()
        assert isinstance(resp, Response)
        assert resp.body == b"hello world"
        assert resp.media_type == "text/plain"

    def test_path_content_produces_file_response(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"file content")
            path = f.name

        fr = FileResult(content=path, media_type="text/plain", filename="test.txt")
        resp = fr.to_response()
        assert isinstance(resp, FileResponse)

    def test_iterator_content_produces_streaming_response(self) -> None:
        def generate():  # type: ignore[no-untyped-def]
            yield b"chunk1"
            yield b"chunk2"

        fr = FileResult(content=generate(), media_type="application/octet-stream")
        resp = fr.to_response()
        assert isinstance(resp, StreamingResponse)

    async def test_async_iterator_produces_streaming_response(self) -> None:
        async def generate():  # type: ignore[no-untyped-def]
            yield b"chunk1"
            yield b"chunk2"

        fr = FileResult(content=generate(), media_type="application/octet-stream")
        resp = fr.to_response()
        assert isinstance(resp, StreamingResponse)

    def test_filename_sets_content_disposition(self) -> None:
        fr = FileResult(content=b"data", media_type="text/csv", filename="export.csv")
        resp = fr.to_response()
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "export.csv" in resp.headers.get("content-disposition", "")

    def test_custom_headers(self) -> None:
        fr = FileResult(content=b"data", headers={"X-Custom": "value"})
        resp = fr.to_response()
        assert resp.headers.get("x-custom") == "value"

    def test_default_media_type(self) -> None:
        fr = FileResult(content=b"data")
        assert fr.media_type == "application/octet-stream"


# ---------------------------------------------------------------------------
# Handler returning Response directly (passthrough)
# ---------------------------------------------------------------------------


class TestResponsePassthrough:
    def test_handler_returning_starlette_response(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="download")
        async def download_handler(intent: Intent, context: AgentContext) -> Response:
            return Response(content=b"raw bytes", media_type="application/octet-stream")

        client = TestClient(app)
        response = client.post("/agent/download", json={"intent": "get file"})
        assert response.status_code == 200
        assert response.content == b"raw bytes"
        assert "application/octet-stream" in response.headers.get("content-type", "")

    def test_handler_returning_streaming_response(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="stream")
        async def stream_handler(intent: Intent, context: AgentContext) -> StreamingResponse:
            async def gen():  # type: ignore[no-untyped-def]
                yield b"hello "
                yield b"world"

            return StreamingResponse(gen(), media_type="text/plain")

        client = TestClient(app)
        response = client.post("/agent/stream", json={"intent": "stream data"})
        assert response.status_code == 200
        assert response.content == b"hello world"

    def test_handler_returning_file_result(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="csv")
        async def csv_handler(intent: Intent, context: AgentContext) -> FileResult:
            return FileResult(
                content=b"name,value\nalice,42",
                media_type="text/csv",
                filename="export.csv",
            )

        client = TestClient(app)
        response = client.post("/agent/csv", json={"intent": "export csv"})
        assert response.status_code == 200
        assert response.content == b"name,value\nalice,42"
        assert "text/csv" in response.headers.get("content-type", "")
        assert "export.csv" in response.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# Backward compatibility: dict and AgentResponse still work as JSON
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_handler_returning_dict_still_json(self) -> None:
        app = AgenticApp()

        @app.agent_endpoint(name="json")
        async def json_handler(intent: Intent, context: AgentContext) -> dict[str, str]:
            return {"message": "hello"}

        client = TestClient(app)
        response = client.post("/agent/json", json={"intent": "hello"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    def test_handler_returning_agent_response_still_json(self) -> None:
        from agenticapi.interface.response import AgentResponse

        app = AgenticApp()

        @app.agent_endpoint(name="resp")
        async def resp_handler(intent: Intent, context: AgentContext) -> AgentResponse:
            return AgentResponse(result={"count": 42}, reasoning="test")

        client = TestClient(app)
        response = client.post("/agent/resp", json={"intent": "count"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
