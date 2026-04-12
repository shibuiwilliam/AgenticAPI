"""Handler signature scanner.

Inspects a handler (or a dependency callable) and produces an
:class:`InjectionPlan` describing how each parameter should be filled
at request time. The plan is computed once per handler at registration
and cached on the :class:`AgentEndpointDef` so request-path code stays
fast.

Three sources of injected values are supported, in priority order:

1. **Built-in injectors** for ``Intent``, ``AgentContext``,
   ``AgentTasks``, ``UploadedFiles``, ``HtmxHeaders``, and
   ``AgentStream`` (the latter when Phase F lands). These are
   recognised by parameter type annotation; the user does not write
   ``Depends(...)``.
2. **User dependencies** declared via ``Depends(...)`` defaults.
3. **Plain positional/keyword fall-through** for handlers that follow
   the legacy ``(intent, context)`` shape with no annotations.

The scanner is annotation-tolerant: it handles ``from __future__
import annotations`` (string annotations are resolved via
:func:`typing.get_type_hints` with ``include_extras=True``).

Phase D4: Typed-intent extraction.
    When a handler declares ``intent: Intent[OrderFilters]``, the
    scanner walks the annotation, extracts the Pydantic model
    parameter, and stores it on :attr:`InjectionPlan.intent_payload_schema`.
    The framework then forwards that schema to ``IntentParser.parse``
    so the LLM is constrained to produce a matching payload.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, get_type_hints

from agenticapi.dependencies.depends import Dependency

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel


class InjectionKind(StrEnum):
    """Categorisation of how a single parameter is filled."""

    INTENT = "intent"
    CONTEXT = "context"
    AGENT_TASKS = "agent_tasks"
    UPLOADED_FILES = "uploaded_files"
    HTMX_HEADERS = "htmx_headers"
    AGENT_STREAM = "agent_stream"
    DEPENDS = "depends"
    POSITIONAL_LEGACY = "positional_legacy"


@dataclass(frozen=True, slots=True)
class ParamPlan:
    """How a single handler parameter is resolved.

    Attributes:
        name: The parameter's name in the handler signature.
        kind: Which injector handles this parameter.
        dependency: The user-supplied :class:`Dependency` for
            ``DEPENDS`` parameters; ``None`` otherwise.
        annotation: The resolved annotation for diagnostics.
    """

    name: str
    kind: InjectionKind
    dependency: Dependency | None = None
    annotation: Any = None


@dataclass(frozen=True, slots=True)
class InjectionPlan:
    """Cached injection plan for a single handler.

    Attributes:
        params: Per-parameter resolution plans, in declaration order.
        legacy_positional_count: How many of the leading parameters
            should receive ``intent``/``context`` positionally for
            handlers that don't annotate them.
        intent_payload_schema: Pydantic model parameter extracted from
            an ``Intent[T]`` annotation, or ``None`` for handlers that
            use bare ``Intent`` or no annotation. Forwarded to the
            ``IntentParser`` so the LLM is constrained to produce a
            payload matching ``T``.
    """

    params: tuple[ParamPlan, ...] = field(default_factory=tuple)
    legacy_positional_count: int = 0
    intent_payload_schema: type[BaseModel] | None = None


def _is_intent_annotation(annotation: Any) -> bool:
    """True when the annotation is the AgenticAPI ``Intent`` (or ``Intent[T]``)."""
    from agenticapi.interface.intent import Intent

    if annotation is Intent:
        return True
    # ``Intent[T]`` is a parametrised generic at runtime; check origin.
    origin = getattr(annotation, "__origin__", None)
    if origin is Intent:
        return True
    # String annotation fallback (when get_type_hints couldn't resolve).
    return bool(isinstance(annotation, str) and annotation.split("[")[0] == "Intent")


def _extract_intent_payload_schema(annotation: Any) -> type[BaseModel] | None:
    """Pull the ``T`` out of ``Intent[T]`` if it is a Pydantic model.

    Returns ``None`` for bare ``Intent``, for ``Intent[Any]``, or for
    annotations the framework can't introspect (e.g. unresolved string
    annotations). Defensive: any failure during introspection silently
    returns ``None`` so a malformed annotation never breaks startup.
    """
    from pydantic import BaseModel

    from agenticapi.interface.intent import Intent

    try:
        origin = getattr(annotation, "__origin__", None)
        if origin is not Intent:
            return None
        args = getattr(annotation, "__args__", ()) or ()
        if not args:
            return None
        candidate = args[0]
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    except (TypeError, AttributeError):
        return None
    return None


def _is_context_annotation(annotation: Any) -> bool:
    """True when the annotation is :class:`agenticapi.runtime.context.AgentContext`."""
    from agenticapi.runtime.context import AgentContext

    if annotation is AgentContext:
        return True
    return bool(isinstance(annotation, str) and "AgentContext" in annotation)


def _is_agent_tasks_annotation(annotation: Any) -> bool:
    from agenticapi.interface.tasks import AgentTasks

    if annotation is AgentTasks:
        return True
    return bool(isinstance(annotation, str) and "AgentTasks" in annotation)


def _is_uploaded_files_annotation(annotation: Any) -> bool:
    from agenticapi.interface.upload import UploadedFiles

    if annotation is UploadedFiles:
        return True
    return bool(isinstance(annotation, str) and "UploadedFiles" in annotation)


def _is_htmx_headers_annotation(annotation: Any) -> bool:
    from agenticapi.interface.htmx import HtmxHeaders

    if annotation is HtmxHeaders:
        return True
    return bool(isinstance(annotation, str) and "HtmxHeaders" in annotation)


def _is_agent_stream_annotation(annotation: Any) -> bool:
    """True when the annotation is :class:`agenticapi.interface.stream.AgentStream`."""
    from agenticapi.interface.stream import AgentStream

    if annotation is AgentStream:
        return True
    return bool(isinstance(annotation, str) and "AgentStream" in annotation)


def scan_handler(handler: Callable[..., Any]) -> InjectionPlan:
    """Scan a handler signature and return its :class:`InjectionPlan`.

    Resolves string annotations via :func:`typing.get_type_hints` so
    ``from __future__ import annotations`` is fully supported. Falls
    back to raw ``inspect.Parameter.annotation`` strings when the
    handler imports something only under ``TYPE_CHECKING``.

    Args:
        handler: The async or sync handler callable to scan.

    Returns:
        An :class:`InjectionPlan` ready for the solver.
    """
    sig = inspect.signature(handler)
    try:
        type_hints = get_type_hints(handler, include_extras=True)
    except Exception:
        type_hints = {}

    params: list[ParamPlan] = []
    legacy_positional_count = 0
    seen_annotated_intent = False
    seen_annotated_context = False
    intent_payload_schema: type[BaseModel] | None = None

    for index, (param_name, param) in enumerate(sig.parameters.items()):
        annotation = type_hints.get(param_name, param.annotation)
        default = param.default

        # 1) Depends(...) default value — highest precedence.
        if isinstance(default, Dependency):
            params.append(
                ParamPlan(
                    name=param_name,
                    kind=InjectionKind.DEPENDS,
                    dependency=default,
                    annotation=annotation,
                )
            )
            continue

        # 2) Built-in annotated injectors.
        if _is_intent_annotation(annotation):
            params.append(ParamPlan(name=param_name, kind=InjectionKind.INTENT, annotation=annotation))
            seen_annotated_intent = True
            # Phase D4: capture the typed payload model from Intent[T]
            # so the framework can constrain LLM output to match.
            if intent_payload_schema is None:
                intent_payload_schema = _extract_intent_payload_schema(annotation)
            continue
        if _is_context_annotation(annotation):
            params.append(ParamPlan(name=param_name, kind=InjectionKind.CONTEXT, annotation=annotation))
            seen_annotated_context = True
            continue
        if _is_agent_tasks_annotation(annotation):
            params.append(ParamPlan(name=param_name, kind=InjectionKind.AGENT_TASKS, annotation=annotation))
            continue
        if _is_uploaded_files_annotation(annotation):
            params.append(ParamPlan(name=param_name, kind=InjectionKind.UPLOADED_FILES, annotation=annotation))
            continue
        if _is_htmx_headers_annotation(annotation):
            params.append(ParamPlan(name=param_name, kind=InjectionKind.HTMX_HEADERS, annotation=annotation))
            continue
        if _is_agent_stream_annotation(annotation):
            params.append(ParamPlan(name=param_name, kind=InjectionKind.AGENT_STREAM, annotation=annotation))
            continue

        # 3) Legacy positional fall-through.
        # Handlers historically accepted ``(intent, context)`` without
        # type annotations. We preserve that by treating the first two
        # unannotated parameters as positional intent/context slots,
        # but only if they haven't already been satisfied by an
        # annotated parameter above.
        if index < 2 and annotation is inspect.Parameter.empty:
            params.append(
                ParamPlan(
                    name=param_name,
                    kind=InjectionKind.POSITIONAL_LEGACY,
                    annotation=None,
                )
            )
            legacy_positional_count += 1
            continue

        # Unknown parameter with no resolver — leave it absent so the
        # call site supplies it (or fails with a clear TypeError).
        params.append(
            ParamPlan(
                name=param_name,
                kind=InjectionKind.POSITIONAL_LEGACY,
                annotation=annotation,
            )
        )

    # If neither Intent nor AgentContext was annotated AND we did not
    # collect any legacy positionals, fall back to legacy positional
    # mode for the first two params (preserves the (intent, context)
    # contract for handlers that use string annotations the type-hint
    # resolver couldn't load).
    if not seen_annotated_intent and not seen_annotated_context and legacy_positional_count == 0:
        # Mark the first up-to-two params as legacy positionals.
        new_params: list[ParamPlan] = []
        for i, plan in enumerate(params):
            if i < 2 and plan.kind not in {
                InjectionKind.AGENT_TASKS,
                InjectionKind.UPLOADED_FILES,
                InjectionKind.HTMX_HEADERS,
                InjectionKind.AGENT_STREAM,
                InjectionKind.DEPENDS,
            }:
                new_params.append(ParamPlan(name=plan.name, kind=InjectionKind.POSITIONAL_LEGACY, annotation=None))
                legacy_positional_count += 1
            else:
                new_params.append(plan)
        params = new_params

    return InjectionPlan(
        params=tuple(params),
        legacy_positional_count=legacy_positional_count,
        intent_payload_schema=intent_payload_schema,
    )


__all__ = ["InjectionKind", "InjectionPlan", "ParamPlan", "scan_handler"]
