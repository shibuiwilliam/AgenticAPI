"""Workflow state base class.

Provides the typed, serialisable base for workflow state that flows
between steps. Subclass with application-specific fields.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WorkflowState(BaseModel):
    """Base class for workflow state.

    Subclass with typed fields to define the data that accumulates
    as steps execute. The state is passed to every step function and
    mutated in place. After each step, the framework serialises it
    (via Pydantic) for checkpointing and persistence.

    The ``wf_current_step``, ``wf_completed_steps``, and
    ``wf_iteration_count`` fields are managed by the framework
    and should not be set by application code.

    Example::

        class AnalysisState(WorkflowState):
            document_text: str = ""
            summary: str = ""
            risk_level: str = "unknown"
    """

    model_config = ConfigDict(extra="allow")

    wf_current_step: str = ""
    wf_completed_steps: list[str] = Field(default_factory=list)
    wf_iteration_count: int = 0
