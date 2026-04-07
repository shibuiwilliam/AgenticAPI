"""Tests for DynamicPipeline."""

from __future__ import annotations

import pytest

from agenticapi.application.pipeline import DynamicPipeline, PipelineStage


def _upper_handler(ctx: dict) -> dict:
    ctx["value"] = ctx.get("value", "").upper()
    return ctx


async def _async_handler(ctx: dict) -> dict:
    ctx["async"] = True
    return ctx


def _append_handler(ctx: dict) -> dict:
    ctx.setdefault("log", []).append("appended")
    return ctx


class TestDynamicPipelineBasics:
    async def test_empty_pipeline(self) -> None:
        pipeline = DynamicPipeline()
        result = await pipeline.execute({"key": "val"})
        assert result.context == {"key": "val"}
        assert result.stages_executed == []

    async def test_base_stages_always_run(self) -> None:
        pipeline = DynamicPipeline(
            base_stages=[PipelineStage("upper", handler=_upper_handler, required=True)],
        )
        result = await pipeline.execute({"value": "hello"})
        assert result.context["value"] == "HELLO"
        assert result.stages_executed == ["upper"]

    async def test_selected_stages(self) -> None:
        pipeline = DynamicPipeline(
            available_stages=[PipelineStage("upper", handler=_upper_handler)],
        )
        result = await pipeline.execute({"value": "hello"}, selected_stages=["upper"])
        assert result.context["value"] == "HELLO"

    async def test_unknown_selected_stage_skipped(self) -> None:
        pipeline = DynamicPipeline()
        result = await pipeline.execute({}, selected_stages=["nonexistent"])
        assert result.stages_executed == []

    async def test_async_handler(self) -> None:
        pipeline = DynamicPipeline(
            base_stages=[PipelineStage("async_stage", handler=_async_handler)],
        )
        result = await pipeline.execute({})
        assert result.context["async"] is True

    async def test_stage_timings_recorded(self) -> None:
        pipeline = DynamicPipeline(
            base_stages=[PipelineStage("upper", handler=_upper_handler)],
        )
        result = await pipeline.execute({"value": "x"})
        assert "upper" in result.stage_timings_ms
        assert result.stage_timings_ms["upper"] >= 0

    async def test_stage_without_handler_skipped(self) -> None:
        pipeline = DynamicPipeline(
            base_stages=[PipelineStage("noop")],
        )
        result = await pipeline.execute({"value": "x"})
        assert result.stages_executed == []


class TestPipelineOrdering:
    async def test_stages_sorted_by_order(self) -> None:
        log: list[str] = []

        def make_handler(name: str):
            def handler(ctx: dict) -> dict:
                log.append(name)
                return ctx

            return handler

        pipeline = DynamicPipeline(
            base_stages=[
                PipelineStage("second", handler=make_handler("second"), order=20),
                PipelineStage("first", handler=make_handler("first"), order=10),
                PipelineStage("third", handler=make_handler("third"), order=30),
            ],
        )
        await pipeline.execute({})
        assert log == ["first", "second", "third"]


class TestPipelineLimits:
    async def test_max_stages_enforced(self) -> None:
        stages = [PipelineStage(f"s{i}", handler=_upper_handler) for i in range(5)]
        pipeline = DynamicPipeline(base_stages=stages, max_stages=3)
        with pytest.raises(ValueError, match="exceeding max"):
            await pipeline.execute({"value": "x"})


class TestPipelineProperties:
    def test_available_stage_names(self) -> None:
        pipeline = DynamicPipeline(
            available_stages=[
                PipelineStage("a"),
                PipelineStage("b"),
            ],
        )
        assert sorted(pipeline.available_stage_names) == ["a", "b"]

    def test_get_stage(self) -> None:
        stage = PipelineStage("cache", description="Cache lookup")
        pipeline = DynamicPipeline(available_stages=[stage])
        assert pipeline.get_stage("cache") is stage
        assert pipeline.get_stage("nonexistent") is None

    def test_base_stages_returns_copy(self) -> None:
        stage = PipelineStage("auth", required=True)
        pipeline = DynamicPipeline(base_stages=[stage])
        stages = pipeline.base_stages
        stages.clear()
        assert len(pipeline.base_stages) == 1
