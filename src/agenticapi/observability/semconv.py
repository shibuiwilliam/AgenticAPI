"""Semantic convention constants for AgenticAPI OpenTelemetry spans.

Centralises every span attribute name in one place so the rest of the
codebase references constants rather than scattered string literals.
This module deliberately splits attributes into two groups:

* :class:`GenAIAttributes` mirrors the upstream OpenTelemetry GenAI SIG
  semantic conventions (``gen_ai.*`` namespace). Using these means
  AgenticAPI traces light up correctly in any APM that already
  understands GenAI workloads (Datadog, Grafana Tempo, Honeycomb,
  New Relic, Arize, Langfuse, etc.).

* :class:`AgenticAPIAttributes` covers the framework-specific extras
  (policy verdicts, autonomy levels, sandbox events, approval IDs)
  that no generic APM has but every operator running an AgenticAPI app
  in production wants to see in their traces.

The constants are :class:`StrEnum` members so the type checker can
catch typos at the call site (``span.set_attribute(GenAIAttributes.MODEL, ...)``
rather than the more error-prone ``"gen_ai.request.model"``).
"""

from __future__ import annotations

from enum import StrEnum


class GenAIAttributes(StrEnum):
    """OpenTelemetry GenAI semantic conventions (``gen_ai.*``).

    Pinned to the stable subset of the OpenTelemetry GenAI SIG
    conventions so AgenticAPI traces interoperate with vendor APMs.
    """

    SYSTEM = "gen_ai.system"
    OPERATION_NAME = "gen_ai.operation.name"

    REQUEST_MODEL = "gen_ai.request.model"
    REQUEST_TEMPERATURE = "gen_ai.request.temperature"
    REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
    REQUEST_TOP_P = "gen_ai.request.top_p"

    RESPONSE_MODEL = "gen_ai.response.model"
    RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"

    USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    USAGE_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read_input_tokens"
    USAGE_CACHE_WRITE_INPUT_TOKENS = "gen_ai.usage.cache_write_input_tokens"

    TOOL_NAME = "gen_ai.tool.name"
    TOOL_CALL_ID = "gen_ai.tool.call.id"


class AgenticAPIAttributes(StrEnum):
    """AgenticAPI-specific span and metric attributes.

    These cover the harness-specific data that no generic APM has but
    every operator running AgenticAPI in production wants to see in
    their traces.
    """

    # Endpoint / request
    ENDPOINT_NAME = "agenticapi.endpoint.name"
    AUTONOMY_LEVEL = "agenticapi.endpoint.autonomy_level"
    REQUEST_TRACE_ID = "agenticapi.trace_id"
    SESSION_ID = "agenticapi.session_id"
    USER_ID = "agenticapi.user_id"

    # Intent
    INTENT_RAW = "agenticapi.intent.raw"
    INTENT_ACTION = "agenticapi.intent.action"
    INTENT_DOMAIN = "agenticapi.intent.domain"
    INTENT_CONFIDENCE = "agenticapi.intent.confidence"
    INTENT_PAYLOAD_SCHEMA = "agenticapi.intent.payload_schema"

    # Code generation
    CODE_LINES = "agenticapi.code.lines"

    # Policy
    POLICY_NAME = "agenticapi.policy.name"
    POLICY_ALLOWED = "agenticapi.policy.allowed"
    POLICY_VIOLATIONS = "agenticapi.policy.violations"

    # Sandbox
    SANDBOX_BACKEND = "agenticapi.sandbox.backend"
    SANDBOX_VIOLATION = "agenticapi.sandbox.violation"
    SANDBOX_DURATION_MS = "agenticapi.sandbox.duration_ms"

    # Approval
    APPROVAL_REQUIRED = "agenticapi.approval.required"
    APPROVAL_REQUEST_ID = "agenticapi.approval.request_id"

    # Cost
    COST_USD = "agenticapi.cost.usd"
    COST_BUDGET_LIMIT = "agenticapi.cost.budget_limit_usd"
    COST_BUDGET_SCOPE = "agenticapi.cost.budget_scope"


class SpanNames(StrEnum):
    """Canonical span names emitted by AgenticAPI instrumentation."""

    AGENT_REQUEST = "agent.request"
    INTENT_PARSE = "agent.intent_parse"
    CODE_GENERATE = "agent.code_generate"
    POLICY_EVALUATE = "agent.policy_evaluate"
    STATIC_ANALYSIS = "agent.static_analysis"
    APPROVAL_WAIT = "agent.approval_wait"
    SANDBOX_EXECUTE = "agent.sandbox_execute"
    AUDIT_RECORD = "agent.audit_record"
    GEN_AI_CHAT = "gen_ai.chat"
    TOOL_CALL = "gen_ai.tool.call"


__all__ = ["AgenticAPIAttributes", "GenAIAttributes", "SpanNames"]
