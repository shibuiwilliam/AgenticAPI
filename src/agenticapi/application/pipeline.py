"""Dynamic pipeline for request processing.

Provides a middleware-like pipeline that agents can dynamically compose
based on request content. Analogous to Starlette's middleware stack,
but with dynamic stage selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineStage:
    """A single stage in a processing pipeline.

    Attributes:
        name: Unique identifier for this stage.
        description: Human-readable description for agent-based selection.
        handler: Async callable that processes the request context.
        required: Whether this stage is always applied (not skippable).
        order: Execution order hint (lower runs first).
    """

    name: str
    description: str = ""
    handler: Any = None  # Callable[[dict[str, Any]], dict[str, Any]]
    required: bool = False
    order: int = 100


@dataclass(slots=True)
class PipelineResult:
    """Result of pipeline execution.

    Attributes:
        context: The final context after all stages.
        stages_executed: Names of stages that ran.
        stage_timings_ms: Execution time per stage in milliseconds.
    """

    context: dict[str, Any]
    stages_executed: list[str] = field(default_factory=list)
    stage_timings_ms: dict[str, float] = field(default_factory=dict)


class DynamicPipeline:
    """Dynamically composed request processing pipeline.

    The pipeline has base stages (always applied) and available stages
    (selected per request based on content). Stages run in order,
    each receiving and returning a context dict.

    Example:
        pipeline = DynamicPipeline(
            base_stages=[PipelineStage("auth", handler=auth_handler, required=True)],
            available_stages=[PipelineStage("cache", description="Cache lookup")],
            max_stages=10,
        )
        result = await pipeline.execute(context, selected_stages=["cache"])
    """

    def __init__(
        self,
        *,
        base_stages: list[PipelineStage] | None = None,
        available_stages: list[PipelineStage] | None = None,
        max_stages: int = 10,
    ) -> None:
        """Initialize the pipeline.

        Args:
            base_stages: Stages always applied to every request.
            available_stages: Stages that can be dynamically selected.
            max_stages: Maximum total stages allowed per execution.
        """
        self._base_stages = list(base_stages) if base_stages else []
        self._available_stages = {s.name: s for s in (available_stages or [])}
        self._max_stages = max_stages

    @property
    def base_stages(self) -> list[PipelineStage]:
        """The base stages always applied."""
        return list(self._base_stages)

    @property
    def available_stage_names(self) -> list[str]:
        """Names of stages available for dynamic selection."""
        return list(self._available_stages.keys())

    def get_stage(self, name: str) -> PipelineStage | None:
        """Look up an available stage by name.

        Args:
            name: The stage name to look up.

        Returns:
            The PipelineStage if found, None otherwise.
        """
        return self._available_stages.get(name)

    async def execute(
        self,
        context: dict[str, Any],
        *,
        selected_stages: list[str] | None = None,
    ) -> PipelineResult:
        """Execute the pipeline with the given context.

        Runs base stages first, then selected stages, all sorted by order.

        Args:
            context: The initial request context.
            selected_stages: Names of dynamic stages to include.

        Returns:
            The pipeline result with final context and execution info.

        Raises:
            ValueError: If total stages exceed max_stages.
        """
        import time

        # Gather all stages to run
        stages: list[PipelineStage] = list(self._base_stages)
        for name in selected_stages or []:
            stage = self._available_stages.get(name)
            if stage is not None:
                stages.append(stage)
            else:
                logger.warning("pipeline_stage_not_found", stage_name=name)

        if len(stages) > self._max_stages:
            raise ValueError(f"Pipeline has {len(stages)} stages, exceeding max of {self._max_stages}")

        # Sort by order
        stages.sort(key=lambda s: s.order)

        result = PipelineResult(context=dict(context))
        for stage in stages:
            if stage.handler is None:
                continue
            start = time.monotonic()
            handler_result = stage.handler(result.context)
            if hasattr(handler_result, "__await__"):
                handler_result = await handler_result
            if isinstance(handler_result, dict):
                result.context = handler_result
            elapsed_ms = (time.monotonic() - start) * 1000
            result.stages_executed.append(stage.name)
            result.stage_timings_ms[stage.name] = elapsed_ms

            logger.debug(
                "pipeline_stage_complete",
                stage=stage.name,
                elapsed_ms=round(elapsed_ms, 2),
            )

        return result
