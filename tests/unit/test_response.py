"""Tests for AgentResponse and ResponseFormatter."""

from __future__ import annotations

from agenticapi.interface.response import AgentResponse, ResponseFormatter


class TestAgentResponse:
    def test_to_dict_basic(self) -> None:
        resp = AgentResponse(result={"count": 42}, status="completed")
        d = resp.to_dict()
        assert d["result"] == {"count": 42}
        assert d["status"] == "completed"
        assert d["confidence"] == 1.0

    def test_to_dict_excludes_none(self) -> None:
        resp = AgentResponse(result="ok", status="completed")
        d = resp.to_dict()
        assert "generated_code" not in d
        assert "reasoning" not in d
        assert "error" not in d
        assert "execution_trace_id" not in d
        assert "approval_request" not in d

    def test_to_dict_includes_non_none(self) -> None:
        resp = AgentResponse(
            result="ok",
            status="completed",
            generated_code="x = 1",
            reasoning="simple",
            execution_trace_id="trace-123",
        )
        d = resp.to_dict()
        assert d["generated_code"] == "x = 1"
        assert d["reasoning"] == "simple"
        assert d["execution_trace_id"] == "trace-123"

    def test_to_dict_with_error(self) -> None:
        resp = AgentResponse(result=None, status="error", error="something broke")
        d = resp.to_dict()
        assert d["error"] == "something broke"
        assert d["status"] == "error"

    def test_follow_up_suggestions_included(self) -> None:
        resp = AgentResponse(
            result="ok",
            status="completed",
            follow_up_suggestions=["Try this", "Or this"],
        )
        d = resp.to_dict()
        assert d["follow_up_suggestions"] == ["Try this", "Or this"]


class TestResponseFormatter:
    def test_format_json(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(result={"data": 1}, status="completed")
        d = formatter.format_json(resp)
        assert d["result"] == {"data": 1}
        assert d["status"] == "completed"

    def test_format_text_completed(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(result="42 orders", status="completed")
        text = formatter.format_text(resp)
        assert "Status: completed" in text
        assert "Result: 42 orders" in text

    def test_format_text_error(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(result=None, status="error", error="oops")
        text = formatter.format_text(resp)
        assert "Error: oops" in text

    def test_format_text_with_reasoning(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(result="ok", status="completed", reasoning="because")
        text = formatter.format_text(resp)
        assert "Reasoning: because" in text

    def test_format_text_confidence_shown_when_less_than_one(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(result="ok", status="completed", confidence=0.75)
        text = formatter.format_text(resp)
        assert "Confidence: 0.75" in text

    def test_format_text_confidence_hidden_when_one(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(result="ok", status="completed", confidence=1.0)
        text = formatter.format_text(resp)
        assert "Confidence" not in text

    def test_format_text_suggestions(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(
            result="ok",
            status="completed",
            follow_up_suggestions=["Do X", "Do Y"],
        )
        text = formatter.format_text(resp)
        assert "Suggestions:" in text
        assert "- Do X" in text
        assert "- Do Y" in text

    def test_format_text_trace_id(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(result="ok", status="completed", execution_trace_id="abc")
        text = formatter.format_text(resp)
        assert "Trace ID: abc" in text


class TestResponseEdgeCases:
    def test_approval_request_serialized(self) -> None:
        resp = AgentResponse(
            result=None,
            status="pending_approval",
            approval_request={"request_id": "req-1", "approvers": ["admin"]},
        )
        d = resp.to_dict()
        assert d["approval_request"]["request_id"] == "req-1"
        assert d["status"] == "pending_approval"

    def test_none_result_serialized(self) -> None:
        resp = AgentResponse(result=None, status="completed")
        d = resp.to_dict()
        # result=None should still be present (it's not excluded)
        assert "status" in d
        assert d["status"] == "completed"

    def test_empty_list_result(self) -> None:
        resp = AgentResponse(result=[], status="completed")
        d = resp.to_dict()
        assert d["result"] == []

    def test_empty_string_result(self) -> None:
        resp = AgentResponse(result="", status="completed")
        d = resp.to_dict()
        assert d["result"] == ""

    def test_pending_approval_format_text(self) -> None:
        formatter = ResponseFormatter()
        resp = AgentResponse(
            result=None,
            status="pending_approval",
            error="Approval required",
        )
        text = formatter.format_text(resp)
        assert "pending_approval" in text
