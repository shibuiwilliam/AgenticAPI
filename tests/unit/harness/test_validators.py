"""Tests for post-execution validators."""

from __future__ import annotations

from agenticapi.harness.sandbox.base import ResourceMetrics, SandboxResult
from agenticapi.harness.sandbox.validators import OutputTypeValidator, ReadOnlyValidator


def _make_result(
    *,
    return_value: object = None,
    stdout: str = "",
    stderr: str = "",
) -> SandboxResult:
    return SandboxResult(
        output=return_value,
        return_value=return_value,
        metrics=ResourceMetrics(cpu_time_ms=10, memory_peak_mb=10, wall_time_ms=10),
        stdout=stdout,
        stderr=stderr,
    )


class TestOutputTypeValidator:
    async def test_json_serializable_passes(self) -> None:
        validator = OutputTypeValidator()
        result = await validator.validate(
            _make_result(return_value={"count": 42, "items": [1, 2, 3]}),
            code="x = 1",
            intent_action="read",
        )
        assert result.valid is True

    async def test_none_return_value_passes(self) -> None:
        validator = OutputTypeValidator()
        result = await validator.validate(
            _make_result(return_value=None),
            code="x = 1",
            intent_action="read",
        )
        assert result.valid is True

    async def test_string_passes(self) -> None:
        validator = OutputTypeValidator()
        result = await validator.validate(
            _make_result(return_value="hello"),
            code="x = 1",
            intent_action="read",
        )
        assert result.valid is True

    async def test_list_passes(self) -> None:
        validator = OutputTypeValidator()
        result = await validator.validate(
            _make_result(return_value=[1, 2, 3]),
            code="x = 1",
            intent_action="read",
        )
        assert result.valid is True


class TestReadOnlyValidator:
    async def test_read_intent_clean_output_passes(self) -> None:
        validator = ReadOnlyValidator()
        result = await validator.validate(
            _make_result(stdout="result: 42"),
            code="x = 1",
            intent_action="read",
        )
        assert result.valid is True
        assert len(result.warnings) == 0

    async def test_read_intent_write_pattern_warns(self) -> None:
        validator = ReadOnlyValidator()
        result = await validator.validate(
            _make_result(stdout="INSERT INTO users VALUES (1, 'test')"),
            code="x = 1",
            intent_action="read",
        )
        assert result.valid is True  # warnings only, not blocking
        assert len(result.warnings) > 0
        assert any("INSERT INTO" in w for w in result.warnings)

    async def test_write_intent_allows_write_patterns(self) -> None:
        validator = ReadOnlyValidator()
        result = await validator.validate(
            _make_result(stdout="DELETE FROM orders"),
            code="x = 1",
            intent_action="write",
        )
        assert result.valid is True
        assert len(result.warnings) == 0

    async def test_read_intent_stderr_write_pattern_warns(self) -> None:
        validator = ReadOnlyValidator()
        result = await validator.validate(
            _make_result(stderr="DROP TABLE users"),
            code="x = 1",
            intent_action="read",
        )
        assert result.valid is True
        assert len(result.warnings) > 0

    async def test_multiple_write_patterns_detected(self) -> None:
        validator = ReadOnlyValidator()
        result = await validator.validate(
            _make_result(stdout="INSERT INTO x UPDATE y"),
            code="x = 1",
            intent_action="read",
        )
        assert len(result.warnings) >= 2
