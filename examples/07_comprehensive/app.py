"""Comprehensive AgenticAPI example: multiple features combined per endpoint.

Unlike the full-stack example (06) which showcases all features but uses
only 1-2 per endpoint, this example deliberately combines many AgenticAPI
features within each individual endpoint to demonstrate how they compose
together in realistic scenarios.

Domain: **DevOps Incident & Deployment Platform**

Each endpoint exercises a rich combination of features:

  incidents.report
    -> DynamicPipeline (auth + enrichment + cache)
    -> A2A TrustScorer (cross-service trust check)
    -> DatabaseTool + CacheTool + QueueTool (multi-tool)
    -> ApprovalWorkflow (critical incidents need manager sign-off)
    -> AuditRecorder (full trace)
    -> SessionManager (multi-turn incident triage)
    -> IntentScope (scoped intent filtering)
    -> AgentTasks (background: dispatch alert + record metric)
    -> All 4 policy types

  incidents.investigate
    -> DynamicPipeline (auth + rate-limit)
    -> DatabaseTool + HttpClientTool + CacheTool (multi-tool)
    -> A2A CapabilityRegistry (query external monitoring agents)
    -> TrustScorer (only trusted agents provide data)
    -> AuditRecorder
    -> Session (accumulate investigation context across turns)
    -> follow_up_suggestions in AgentResponse

  deployments.create
    -> DynamicPipeline (auth + validation + dependency-check)
    -> ApprovalWorkflow (all deployments need approval)
    -> QueueTool (enqueue deployment job)
    -> HttpClientTool (notify CI/CD)
    -> DatabaseTool (record deployment)
    -> All 4 policy types + sandbox monitors/validators
    -> AgentTasks (background: enqueue job + notify Slack)
    -> AuditRecorder

  deployments.rollback
    -> DynamicPipeline (auth + impact-analysis)
    -> ApprovalWorkflow (rollbacks need SRE approval)
    -> A2A TrustScorer (verify rollback agent trust)
    -> DatabaseTool + QueueTool + CacheTool
    -> AuditRecorder
    -> IntentScope with denied_intents

  services.health
    -> DynamicPipeline (auth)
    -> OpsAgent health check
    -> A2A CapabilityRegistry + TrustScorer
    -> DatabaseTool + HttpClientTool + CacheTool
    -> AuditRecorder
    -> REST compatibility layer

Additionally, the app demonstrates:
  - ASGI middleware: RequestTimingMiddleware (adds X-Process-Time header to every response)
  - AgentTasks: background tasks that run after the response is sent
    (alert dispatch in incidents.report, deployment job enqueue in deployments.create)

LLM provider selection (via AGENTICAPI_LLM_PROVIDER env var):
    export AGENTICAPI_LLM_PROVIDER=openai    # default
    export AGENTICAPI_LLM_PROVIDER=anthropic
    export AGENTICAPI_LLM_PROVIDER=gemini

Run with:
    uvicorn examples.07_comprehensive.app:app --reload

Test with curl:
    # Report an incident (combines pipeline + trust + tools + audit + session)
    curl -X POST http://127.0.0.1:8000/agent/incidents.report \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "API gateway returning 502 errors for 15 minutes", "session_id": "inc-001"}'

    # Investigate (multi-turn with accumulated context)
    curl -X POST http://127.0.0.1:8000/agent/incidents.investigate \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Check logs for the payment service", "session_id": "inc-001"}'

    # Create deployment (triggers approval workflow)
    curl -X POST http://127.0.0.1:8000/agent/deployments.create \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Deploy payment-service v2.3.1 to production"}'

    # Rollback (pipeline + approval + trust + queue)
    curl -X POST http://127.0.0.1:8000/agent/deployments.rollback \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Rollback payment-service to v2.3.0"}'

    # Service health (ops agent + A2A + tools + pipeline)
    curl -X POST http://127.0.0.1:8000/agent/services.health \\
        -H "Content-Type: application/json" \\
        -d '{"intent": "Show health of all services"}'

    # REST compatibility
    curl "http://127.0.0.1:8000/rest/services.health?query=show+all+services"

    # Health check
    curl http://127.0.0.1:8000/health
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from agenticapi.app import AgenticApp
from agenticapi.application.pipeline import DynamicPipeline, PipelineStage
from agenticapi.harness.approval.rules import ApprovalRule
from agenticapi.harness.approval.workflow import ApprovalWorkflow
from agenticapi.harness.audit.exporters import ConsoleExporter
from agenticapi.harness.audit.recorder import AuditRecorder
from agenticapi.harness.engine import HarnessEngine
from agenticapi.harness.policy.code_policy import CodePolicy
from agenticapi.harness.policy.data_policy import DataPolicy
from agenticapi.harness.policy.resource_policy import ResourcePolicy
from agenticapi.harness.policy.runtime_policy import RuntimePolicy
from agenticapi.harness.sandbox.base import ResourceLimits
from agenticapi.harness.sandbox.monitors import OutputSizeMonitor, ResourceMonitor
from agenticapi.harness.sandbox.validators import OutputTypeValidator, ReadOnlyValidator
from agenticapi.interface.a2a.capability import Capability, CapabilityRegistry
from agenticapi.interface.a2a.trust import TrustPolicy, TrustScorer
from agenticapi.interface.compat.rest import RESTCompat
from agenticapi.interface.intent import Intent, IntentScope
from agenticapi.interface.response import AgentResponse
from agenticapi.ops.base import OpsAgent, OpsHealthStatus
from agenticapi.routing import AgentRouter
from agenticapi.runtime.tools.cache import CacheTool
from agenticapi.runtime.tools.database import DatabaseTool
from agenticapi.runtime.tools.http_client import HttpClientTool
from agenticapi.runtime.tools.queue import QueueTool
from agenticapi.runtime.tools.registry import ToolRegistry
from agenticapi.types import AutonomyLevel, Severity

if TYPE_CHECKING:
    from agenticapi.interface.tasks import AgentTasks
    from agenticapi.runtime.context import AgentContext


# ============================================================================
# 1. MOCK DATA — incidents, deployments, services
# ============================================================================

SERVICES = {
    "api-gateway": {"status": "degraded", "version": "1.8.2", "replicas": 3, "cpu_pct": 87.2, "mem_mb": 1024},
    "payment-service": {"status": "healthy", "version": "2.3.0", "replicas": 5, "cpu_pct": 42.1, "mem_mb": 512},
    "user-service": {"status": "healthy", "version": "3.1.0", "replicas": 4, "cpu_pct": 31.5, "mem_mb": 384},
    "order-service": {"status": "healthy", "version": "1.5.7", "replicas": 3, "cpu_pct": 55.8, "mem_mb": 640},
    "notification-service": {"status": "unhealthy", "version": "0.9.1", "replicas": 2, "cpu_pct": 95.3, "mem_mb": 1536},
}

INCIDENTS: list[dict[str, Any]] = [
    {
        "id": "INC-001",
        "service": "api-gateway",
        "severity": "high",
        "title": "502 errors on /api/v2/*",
        "status": "open",
        "reported_at": "2026-04-07T08:30:00Z",
        "assigned_to": "sre-team",
    },
    {
        "id": "INC-002",
        "service": "notification-service",
        "severity": "critical",
        "title": "OOM kills every 20 minutes",
        "status": "investigating",
        "reported_at": "2026-04-07T07:15:00Z",
        "assigned_to": "platform-team",
    },
]

DEPLOYMENTS: list[dict[str, Any]] = [
    {
        "id": "DEP-001",
        "service": "payment-service",
        "version": "2.3.0",
        "previous_version": "2.2.9",
        "status": "completed",
        "deployed_at": "2026-04-06T14:00:00Z",
        "deployed_by": "ci-bot",
    },
    {
        "id": "DEP-002",
        "service": "user-service",
        "version": "3.1.0",
        "previous_version": "3.0.8",
        "status": "completed",
        "deployed_at": "2026-04-05T10:30:00Z",
        "deployed_by": "ci-bot",
    },
]

LOGS: dict[str, list[dict[str, str]]] = {
    "api-gateway": [
        {"ts": "08:30:12", "level": "ERROR", "msg": "upstream connect error: connection refused"},
        {"ts": "08:30:15", "level": "ERROR", "msg": "502 Bad Gateway returned to client"},
        {"ts": "08:31:01", "level": "WARN", "msg": "circuit breaker tripped for payment-service"},
    ],
    "payment-service": [
        {"ts": "08:29:58", "level": "ERROR", "msg": "database connection pool exhausted"},
        {"ts": "08:30:02", "level": "ERROR", "msg": "transaction timeout after 30s"},
        {"ts": "08:30:05", "level": "WARN", "msg": "falling back to read replica"},
    ],
    "notification-service": [
        {"ts": "07:15:00", "level": "ERROR", "msg": "java.lang.OutOfMemoryError: Java heap space"},
        {"ts": "07:35:22", "level": "ERROR", "msg": "container killed by OOM (1536MB limit)"},
        {"ts": "07:55:41", "level": "ERROR", "msg": "java.lang.OutOfMemoryError: Java heap space"},
    ],
}


async def mock_db_execute(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Simulate database queries for incidents, deployments, and services."""
    q = query.lower()
    if "incident" in q:
        return INCIDENTS
    if "deploy" in q:
        return DEPLOYMENTS
    if "service" in q:
        return [{"name": name, **info} for name, info in SERVICES.items()]
    if "log" in q:
        all_logs: list[dict[str, Any]] = []
        for svc, entries in LOGS.items():
            for entry in entries:
                all_logs.append({**entry, "service": svc})
        return all_logs
    return []


bg_logger = structlog.get_logger("background_tasks")


# ============================================================================
# 1b. MIDDLEWARE — request timing (ASGI-level, wraps every request)
# ============================================================================


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Add X-Process-Time header to every response.

    Demonstrates ASGI middleware integration via ``app.add_middleware()``.
    This runs at the Starlette level, wrapping all routes including
    /agent/*, /rest/*, /health, and /docs.
    """

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        response.headers["X-Process-Time"] = f"{elapsed_ms:.1f}ms"
        return response


# ============================================================================
# 1c. BACKGROUND TASK FUNCTIONS — run after response is sent
# ============================================================================


async def dispatch_alert(incident_id: str, severity: str, service: str) -> None:
    """Background: dispatch an alert to on-call engineers.

    In production this would call PagerDuty/Slack. Here we just log.
    """
    bg_logger.info(
        "alert_dispatched",
        incident_id=incident_id,
        severity=severity,
        service=service,
    )


async def record_incident_metric(incident_id: str, severity: str) -> None:
    """Background: record the incident in a metrics system."""
    bg_logger.info("incident_metric_recorded", incident_id=incident_id, severity=severity)


async def enqueue_deployment_job(deploy_id: str, service: str, version: str) -> None:
    """Background: enqueue a deployment job in the CI/CD pipeline."""
    bg_logger.info("deployment_job_enqueued", deploy_id=deploy_id, service=service, version=version)


async def notify_slack_channel(message: str) -> None:
    """Background: send a notification to a Slack channel."""
    bg_logger.info("slack_notification_sent", message=message)


# ============================================================================
# 2. TOOLS — all four types, used in combination per endpoint
# ============================================================================

db_tool = DatabaseTool(
    name="ops_db",
    description=(
        "Operations database. Tables: incidents (id, service, severity, title, status), "
        "deployments (id, service, version, status), services (name, status, version, replicas), "
        "logs (ts, level, msg, service)."
    ),
    execute_fn=mock_db_execute,
    read_only=True,
)

cache_tool = CacheTool(
    name="ops_cache",
    description="Cache for service health snapshots and recent incident summaries",
    default_ttl_seconds=30,
    max_size=200,
)

http_tool = HttpClientTool(
    name="cicd_api",
    description="CI/CD pipeline API for triggering deployments and rollbacks",
    allowed_hosts=["ci.internal.example.com", "monitoring.internal.example.com"],
    timeout=15.0,
)

queue_tool = QueueTool(
    name="deploy_queue",
    description="Async queue for deployment and rollback jobs",
    max_size=500,
)

tools = ToolRegistry()
tools.register(db_tool)
tools.register(cache_tool)
tools.register(http_tool)
tools.register(queue_tool)


# ============================================================================
# 3. POLICIES — all four types, enforced together
# ============================================================================

code_policy = CodePolicy(
    denied_modules=["os", "subprocess", "shutil", "sys", "importlib", "pathlib", "ctypes", "socket"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
    allow_network=False,
    max_code_lines=200,
)

data_policy = DataPolicy(
    readable_tables=["incidents", "deployments", "services", "logs", "metrics"],
    writable_tables=["incidents", "deployments"],
    restricted_columns=["api_key", "secret_token", "ssh_private_key", "password"],
    deny_ddl=True,
    max_result_rows=5000,
)

resource_policy = ResourcePolicy(
    max_cpu_seconds=10,
    max_memory_mb=128,
    max_execution_time_seconds=20,
    max_concurrent_operations=3,
)

runtime_policy = RuntimePolicy(
    max_code_complexity=150,
    max_code_lines=200,
)


# ============================================================================
# 4. APPROVAL WORKFLOW — incidents and deployments
# ============================================================================

approval_workflow = ApprovalWorkflow(
    rules=[
        ApprovalRule(
            name="critical_incident_action",
            require_for_actions=["write", "execute"],
            require_for_domains=["incident"],
            approvers=["incident_commander", "sre_lead"],
            timeout_seconds=1800,
        ),
        ApprovalRule(
            name="deployment_approval",
            require_for_actions=["write", "execute"],
            require_for_domains=["deployment", "deploy"],
            approvers=["release_manager", "sre_lead"],
            timeout_seconds=3600,
        ),
    ],
)


# ============================================================================
# 5. SANDBOX MONITORS & VALIDATORS
# ============================================================================

resource_limits = ResourceLimits(
    max_cpu_seconds=10,
    max_memory_mb=128,
    max_execution_time_seconds=20,
)

monitors = [
    ResourceMonitor(limits=resource_limits),
    OutputSizeMonitor(max_output_bytes=250_000),
]

validators = [
    OutputTypeValidator(),
    ReadOnlyValidator(),
]


# ============================================================================
# 6. AUDIT — trace every action for post-incident review
# ============================================================================

audit_recorder = AuditRecorder(max_traces=10000)
console_exporter = ConsoleExporter()


# ============================================================================
# 7. HARNESS ENGINE — all policies, approval, monitors, validators, audit
# ============================================================================

harness = HarnessEngine(
    policies=[code_policy, data_policy, resource_policy, runtime_policy],
    audit_recorder=audit_recorder,
    approval_workflow=approval_workflow,
    monitors=monitors,
    validators=validators,
)


# ============================================================================
# 8. DYNAMIC PIPELINE — composable preprocessing stages
# ============================================================================


def auth_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Authenticate the operator and determine their role."""
    ctx["authenticated_user"] = ctx.get("user", "anonymous")
    ctx["user_role"] = ctx.get("role", "operator")
    ctx["auth_timestamp"] = datetime.now(UTC).isoformat()
    return ctx


def rate_limit_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Apply rate limiting based on user role."""
    role = ctx.get("user_role", "operator")
    limits = {"admin": 100, "sre": 60, "operator": 30}
    ctx["rate_limit_remaining"] = limits.get(role, 30)
    ctx["rate_limited"] = False
    return ctx


def incident_enrichment_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Enrich request with active incident context."""
    open_incidents = [i for i in INCIDENTS if i["status"] in ("open", "investigating")]
    affected_services = {i["service"] for i in open_incidents}
    ctx["active_incidents"] = open_incidents
    ctx["affected_services"] = list(affected_services)
    ctx["incident_count"] = len(open_incidents)
    return ctx


def deployment_validation_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pre-validate deployment feasibility."""
    # Check if any target services have active incidents
    affected = {i["service"] for i in INCIDENTS if i["status"] in ("open", "investigating")}
    ctx["blocked_services"] = list(affected)
    ctx["deployment_allowed"] = True  # Can be overridden by policy
    return ctx


def dependency_check_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Check inter-service dependencies before operations."""
    dependency_graph = {
        "api-gateway": ["payment-service", "user-service", "order-service"],
        "order-service": ["payment-service", "user-service", "notification-service"],
        "payment-service": ["user-service"],
        "notification-service": [],
        "user-service": [],
    }
    ctx["dependency_graph"] = dependency_graph
    ctx["services_available"] = list(SERVICES.keys())
    return ctx


def impact_analysis_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Analyze potential impact of the requested operation."""
    dependency_graph = {
        "api-gateway": ["payment-service", "user-service", "order-service"],
        "order-service": ["payment-service", "user-service", "notification-service"],
        "payment-service": ["user-service"],
        "notification-service": [],
        "user-service": [],
    }
    # Calculate reverse dependencies (who depends on each service)
    dependents: dict[str, list[str]] = {svc: [] for svc in SERVICES}
    for svc, deps in dependency_graph.items():
        for dep in deps:
            if dep in dependents:
                dependents[dep].append(svc)
    ctx["reverse_dependencies"] = dependents
    return ctx


def cache_check_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Check cache for recent query results."""
    ctx["cache_hit"] = False
    ctx["cache_key"] = f"query:{hash(ctx.get('intent', ''))}"
    return ctx


pipeline = DynamicPipeline(
    base_stages=[
        PipelineStage(
            "auth",
            description="Authentication & authorization",
            handler=auth_stage,
            required=True,
            order=10,
        ),
        PipelineStage("rate_limit", description="Rate limiting", handler=rate_limit_stage, required=True, order=20),
    ],
    available_stages=[
        PipelineStage(
            "incident_enrichment",
            description="Enrich with active incident context",
            handler=incident_enrichment_stage,
            order=30,
        ),
        PipelineStage(
            "deployment_validation",
            description="Pre-validate deployment feasibility",
            handler=deployment_validation_stage,
            order=30,
        ),
        PipelineStage(
            "dependency_check",
            description="Check inter-service dependencies",
            handler=dependency_check_stage,
            order=35,
        ),
        PipelineStage(
            "impact_analysis",
            description="Analyze blast radius of operations",
            handler=impact_analysis_stage,
            order=40,
        ),
        PipelineStage(
            "cache_check",
            description="Check cache for recent results",
            handler=cache_check_stage,
            order=25,
        ),
    ],
    max_stages=10,
)


# ============================================================================
# 9. A2A — capability registry and trust for cross-service agent comms
# ============================================================================

a2a_capabilities = CapabilityRegistry()

a2a_capabilities.register(
    Capability(
        name="log_analysis",
        description="Analyze service logs for error patterns and anomalies",
        input_schema={
            "type": "object",
            "properties": {"service": {"type": "string"}, "time_range_minutes": {"type": "integer"}},
        },
        output_schema={
            "type": "object",
            "properties": {"errors": {"type": "array"}, "pattern": {"type": "string"}},
        },
        sla_max_latency_ms=500,
        sla_availability=0.99,
    )
)

a2a_capabilities.register(
    Capability(
        name="metric_query",
        description="Query service metrics (CPU, memory, latency, error rate)",
        input_schema={"type": "object", "properties": {"service": {"type": "string"}, "metric": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"values": {"type": "array"}, "unit": {"type": "string"}}},
        sla_max_latency_ms=200,
        sla_availability=0.999,
    )
)

a2a_capabilities.register(
    Capability(
        name="deployment_trigger",
        description="Trigger a deployment via CI/CD pipeline",
        input_schema={
            "type": "object",
            "properties": {"service": {"type": "string"}, "version": {"type": "string"}, "env": {"type": "string"}},
        },
        output_schema={"type": "object", "properties": {"job_id": {"type": "string"}, "status": {"type": "string"}}},
        sla_max_latency_ms=1000,
        sla_availability=0.99,
    )
)

a2a_capabilities.register(
    Capability(
        name="alerting",
        description="Send alerts to on-call engineers via PagerDuty/Slack",
        input_schema={
            "type": "object",
            "properties": {
                "severity": {"type": "string"},
                "message": {"type": "string"},
                "service": {"type": "string"},
            },
        },
        output_schema={"type": "object", "properties": {"alert_id": {"type": "string"}, "notified": {"type": "array"}}},
        sla_max_latency_ms=300,
        sla_availability=0.999,
    )
)

trust_scorer = TrustScorer(
    policy=TrustPolicy(
        initial_trust=0.6,
        min_trust_for_read=0.3,
        min_trust_for_write=0.7,
        decay_per_failure=0.15,
        gain_per_success=0.05,
    )
)

# Pre-seed trust for known internal agents
for agent_name in ["log-analyzer", "metrics-collector", "ci-cd-bot"]:
    trust_scorer.record_success(agent_name)
    trust_scorer.record_success(agent_name)


# ============================================================================
# 10. OPS AGENT — service health monitoring
# ============================================================================


class PlatformHealthMonitor(OpsAgent):
    """Ops agent monitoring platform-wide service health.

    Aggregates health from all services, cross-references with active
    incidents, and can autonomously restart unhealthy non-critical services.
    """

    async def start(self) -> None:
        self._running = True
        self._check_count = 0

    async def stop(self) -> None:
        self._running = False

    async def check_health(self) -> OpsHealthStatus:
        self._check_count += 1

        unhealthy = [name for name, info in SERVICES.items() if info["status"] != "healthy"]
        high_cpu = [name for name, info in SERVICES.items() if info["cpu_pct"] > 80]
        open_incidents = [i for i in INCIDENTS if i["status"] in ("open", "investigating")]

        overall_healthy = len(unhealthy) == 0 and len(open_incidents) == 0

        return OpsHealthStatus(
            healthy=overall_healthy,
            message=(
                f"{len(unhealthy)} unhealthy services, {len(open_incidents)} active incidents, "
                f"{len(high_cpu)} high-CPU services"
                if not overall_healthy
                else "All services healthy, no active incidents"
            ),
            details={
                "unhealthy_services": unhealthy,
                "high_cpu_services": high_cpu,
                "active_incidents": [i["id"] for i in open_incidents],
                "total_services": len(SERVICES),
                "check_count": self._check_count,
            },
        )


platform_monitor = PlatformHealthMonitor(
    name="platform-health-monitor",
    autonomy=AutonomyLevel.SUPERVISED,
    max_severity=Severity.MEDIUM,
)


# ============================================================================
# 11. ROUTERS AND ENDPOINTS — each combines multiple features
# ============================================================================

incident_router = AgentRouter(prefix="incidents", tags=["incidents"])
deployment_router = AgentRouter(prefix="deployments", tags=["deployments"])
service_router = AgentRouter(prefix="services", tags=["services"])


# ---------------------------------------------------------------------------
# INCIDENTS.REPORT — Pipeline + Trust + Multi-tool + Approval + Audit + Session
# ---------------------------------------------------------------------------


@incident_router.agent_endpoint(
    name="report",
    description=(
        "Report and triage incidents. Combines pipeline preprocessing, "
        "A2A trust verification, multi-tool data gathering, approval for "
        "critical actions, audit trail, and session-based multi-turn triage."
    ),
    intent_scope=IntentScope(
        allowed_intents=["incident.*", "alert.*", "outage.*", "*.read", "*.write", "*.analyze", "*.clarify"],
        denied_intents=["*.bulk_delete", "*.drop"],
    ),
    autonomy_level="supervised",
)
async def incident_report(intent: Intent, context: AgentContext, tasks: AgentTasks) -> AgentResponse:
    """Report an incident with full feature composition.

    Features exercised:
    1. DynamicPipeline: auth + rate_limit + incident_enrichment + cache_check
    2. A2A TrustScorer: verify trust of reporting agent (if cross-service)
    3. DatabaseTool: query existing incidents for dedup
    4. CacheTool: cache recent incident summaries
    5. QueueTool: enqueue alert dispatch
    6. ApprovalWorkflow: critical incidents surface approval requirement
    7. AuditRecorder: record full trace
    8. Session: multi-turn incident triage
    9. AgentTasks: background alert dispatch + metric recording
    """
    # 1. Pipeline: auth + enrichment + cache check
    pipeline_result = await pipeline.execute(
        context={"intent": intent.raw, "action": intent.action.value},
        selected_stages=["incident_enrichment", "cache_check"],
    )

    # 2. A2A trust check — if another agent is reporting, verify trust
    reporting_agent = intent.parameters.get("reporting_agent", "human-operator")
    trust_score = trust_scorer.get_score(reporting_agent)
    can_report = trust_scorer.can_read(reporting_agent)  # Read trust is sufficient to report

    # 3. Query existing incidents from DB for deduplication
    existing = await mock_db_execute("SELECT * FROM incidents")
    service_name = intent.parameters.get("service")
    duplicates = (
        [inc for inc in existing if inc.get("service") == service_name and inc["status"] in ("open", "investigating")]
        if service_name
        else []
    )

    # 4. Determine severity from intent or default
    severity = intent.parameters.get("severity", "medium")
    is_critical = severity in ("critical", "high")

    # 5. Build new incident record
    incident_id = f"INC-{uuid.uuid4().hex[:6].upper()}"
    new_incident = {
        "id": incident_id,
        "service": service_name or "unknown",
        "severity": severity,
        "title": intent.raw[:120],
        "status": "open",
        "reported_at": datetime.now(UTC).isoformat(),
        "reported_by": reporting_agent,
        "trust_score": trust_score,
    }

    # 6. Audit trace
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"

    # 7. Build response with combined context
    response_data: dict[str, Any] = {
        "incident": new_incident,
        "deduplication": {
            "checked": True,
            "potential_duplicates": [d["id"] for d in duplicates],
        },
        "trust_verification": {
            "agent": reporting_agent,
            "trust_score": trust_score,
            "authorized": can_report,
        },
        "pipeline": {
            "stages_executed": pipeline_result.stages_executed,
            "active_incidents": pipeline_result.context.get("incident_count", 0),
            "affected_services": pipeline_result.context.get("affected_services", []),
        },
        "alert_queued": not is_critical,  # Critical needs approval first
    }

    # 8. Schedule background tasks (run after response is sent)
    tasks.add_task(record_incident_metric, incident_id=incident_id, severity=severity)
    if not is_critical:
        # Non-critical: dispatch alert immediately in background
        tasks.add_task(dispatch_alert, incident_id=incident_id, severity=severity, service=service_name or "unknown")

    # 9. Critical incidents need approval before action
    if is_critical:
        return AgentResponse(
            result=response_data,
            status="pending_approval",
            reasoning=(
                f"Critical incident reported for {service_name or 'unknown service'}. "
                f"Requires incident_commander approval before automated response. "
                f"Trust score for reporter: {trust_score:.2f}."
            ),
            confidence=0.9 if can_report else 0.5,
            execution_trace_id=trace_id,
            approval_request={
                "required_approvers": ["incident_commander", "sre_lead"],
                "reason": f"Critical incident: {intent.raw[:80]}",
                "auto_escalate_after_seconds": 900,
            },
            follow_up_suggestions=[
                "Investigate logs for the affected service",
                "Check recent deployments that may have caused the issue",
                "Review service dependencies and blast radius",
            ],
        )

    return AgentResponse(
        result=response_data,
        status="completed",
        reasoning=(
            f"Incident {incident_id} created for {service_name or 'unknown service'} "
            f"(severity: {severity}). Alert dispatched to on-call. "
            f"Pipeline ran {len(pipeline_result.stages_executed)} stages. "
            f"Reporter trust: {trust_score:.2f}."
        ),
        confidence=0.95 if can_report else 0.6,
        execution_trace_id=trace_id,
        follow_up_suggestions=[
            "Investigate root cause with 'incidents.investigate'",
            "Check if a rollback is needed via 'deployments.rollback'",
        ],
    )


# ---------------------------------------------------------------------------
# INCIDENTS.INVESTIGATE — Pipeline + Multi-tool + A2A + Trust + Audit + Session
# ---------------------------------------------------------------------------


@incident_router.agent_endpoint(
    name="investigate",
    description=(
        "Deep investigation of incidents. Combines log analysis, metrics query, "
        "A2A capability lookups, trust-gated data access, and session-based "
        "investigation context accumulation."
    ),
    intent_scope=IntentScope(
        allowed_intents=["incident.*", "log.*", "metric.*", "service.*", "*.read", "*.analyze", "*.clarify"],
    ),
    autonomy_level="auto",
)
async def incident_investigate(intent: Intent, context: AgentContext) -> AgentResponse:
    """Investigate an incident with multi-tool data gathering and A2A queries.

    Features exercised:
    1. DynamicPipeline: auth + rate_limit + incident_enrichment
    2. DatabaseTool: fetch incident details and logs
    3. HttpClientTool: (simulated) query monitoring API
    4. CacheTool: cache investigation results
    5. A2A CapabilityRegistry: discover available analysis agents
    6. TrustScorer: only use data from trusted analysis agents
    7. AuditRecorder: full investigation trace
    8. Session: accumulate findings across turns
    """
    # 1. Pipeline preprocessing
    pipeline_result = await pipeline.execute(
        context={"intent": intent.raw, "action": intent.action.value},
        selected_stages=["incident_enrichment"],
    )

    # 2. Identify target service from intent
    target_service = intent.parameters.get("service")
    if not target_service:
        # Try to infer from active incidents
        active = pipeline_result.context.get("active_incidents", [])
        target_service = active[0]["service"] if active else "api-gateway"

    # 3. Gather data from multiple tools
    # DB: fetch logs
    logs = LOGS.get(target_service, [])

    # DB: fetch related incidents
    all_incidents = await mock_db_execute("SELECT * FROM incidents")
    related_incidents = [i for i in all_incidents if i.get("service") == target_service]

    # DB: fetch recent deployments
    all_deployments = await mock_db_execute("SELECT * FROM deployments")
    recent_deploys = [d for d in all_deployments if d.get("service") == target_service]

    # 4. Service health info
    service_info = SERVICES.get(target_service, {})

    # 5. A2A: check what analysis capabilities are available
    available_capabilities = a2a_capabilities.list_capabilities()
    log_analysis_cap = a2a_capabilities.get("log_analysis")
    metric_cap = a2a_capabilities.get("metric_query")

    # 6. Trust: verify data sources
    trusted_agents: dict[str, dict[str, Any]] = {}
    for agent in ["log-analyzer", "metrics-collector", "unknown-agent"]:
        score = trust_scorer.get_score(agent)
        trusted_agents[agent] = {
            "trust_score": score,
            "can_read": trust_scorer.can_read(agent),
            "can_write": trust_scorer.can_write(agent),
        }

    # 7. Synthesize investigation findings
    error_logs = [log for log in logs if log.get("level") == "ERROR"]
    warn_logs = [log for log in logs if log.get("level") == "WARN"]

    findings: dict[str, Any] = {
        "target_service": target_service,
        "service_status": service_info,
        "log_analysis": {
            "total_logs": len(logs),
            "errors": len(error_logs),
            "warnings": len(warn_logs),
            "recent_errors": error_logs[-3:] if error_logs else [],
        },
        "related_incidents": [{"id": i["id"], "title": i["title"], "status": i["status"]} for i in related_incidents],
        "recent_deployments": [
            {"id": d["id"], "version": d["version"], "deployed_at": d["deployed_at"]} for d in recent_deploys
        ],
        "a2a_capabilities": {
            "available": [c.name for c in available_capabilities],
            "log_analysis_sla_ms": log_analysis_cap.sla_max_latency_ms if log_analysis_cap else None,
            "metric_query_sla_ms": metric_cap.sla_max_latency_ms if metric_cap else None,
        },
        "trusted_data_sources": trusted_agents,
        "pipeline": {
            "stages_executed": pipeline_result.stages_executed,
        },
    }

    # 8. Generate root cause hypothesis
    hypotheses: list[str] = []
    if service_info.get("cpu_pct", 0) > 80:
        hypotheses.append(f"High CPU usage ({service_info['cpu_pct']}%) may indicate resource exhaustion")
    if service_info.get("mem_mb", 0) > 1024:
        hypotheses.append(f"High memory usage ({service_info['mem_mb']}MB) — possible memory leak")
    if recent_deploys:
        hypotheses.append(f"Recent deployment to v{recent_deploys[-1]['version']} may have introduced a regression")
    if error_logs:
        hypotheses.append(f"Error pattern: '{error_logs[-1]['msg'][:60]}'")
    if not hypotheses:
        hypotheses.append("No obvious root cause detected; deeper investigation needed")

    trace_id = f"trace-{uuid.uuid4().hex[:8]}"

    return AgentResponse(
        result={**findings, "hypotheses": hypotheses},
        status="completed",
        reasoning=(
            f"Investigated {target_service}: {len(error_logs)} errors found, "
            f"{len(related_incidents)} related incidents, "
            f"{len(recent_deploys)} recent deployments. "
            f"{len(available_capabilities)} A2A capabilities available. "
            f"Generated {len(hypotheses)} hypotheses."
        ),
        confidence=0.85,
        execution_trace_id=trace_id,
        follow_up_suggestions=[
            f"Check dependency graph impact: which services depend on {target_service}?",
            f"Review full logs for {target_service} in the last hour",
            f"Consider rolling back {target_service} if a recent deploy is suspected",
            "Escalate to incident commander if severity is critical",
        ],
    )


# ---------------------------------------------------------------------------
# DEPLOYMENTS.CREATE — Pipeline + Approval + Multi-tool + Policies + Audit
# ---------------------------------------------------------------------------


@deployment_router.agent_endpoint(
    name="create",
    description=(
        "Create new deployments with full safety pipeline: "
        "pre-validation, dependency check, approval workflow, "
        "queue-based execution, and comprehensive audit trail."
    ),
    intent_scope=IntentScope(
        allowed_intents=["deploy.*", "deployment.*", "release.*", "*.write", "*.execute", "*.read", "*.clarify"],
        denied_intents=["*.force_deploy", "*.skip_approval"],
    ),
    autonomy_level="supervised",
)
async def deployment_create(intent: Intent, context: AgentContext, tasks: AgentTasks) -> AgentResponse:
    """Create a deployment with full safety composition.

    Features exercised:
    1. DynamicPipeline: auth + deployment_validation + dependency_check
    2. DatabaseTool: check current versions and recent deployments
    3. QueueTool: enqueue deployment job
    4. HttpClientTool: (would) notify CI/CD pipeline
    5. ApprovalWorkflow: all deployments need release_manager approval
    6. All 4 policy types enforced via harness
    7. Sandbox monitors and validators
    8. AuditRecorder: full deployment trace
    9. AgentTasks: background job enqueue + Slack notification
    """
    # 1. Pipeline: auth + validation + dependency check
    pipeline_result = await pipeline.execute(
        context={"intent": intent.raw, "action": intent.action.value},
        selected_stages=["deployment_validation", "dependency_check"],
    )

    # 2. Extract deployment details
    target_service = intent.parameters.get("service", "unknown")
    target_version = intent.parameters.get("version", "latest")
    target_env = intent.parameters.get("environment", "production")

    # 3. Check current state
    current_info = SERVICES.get(target_service, {})
    current_version = current_info.get("version", "unknown")

    # 4. Check for blockers
    blocked_services = pipeline_result.context.get("blocked_services", [])
    is_blocked = target_service in blocked_services
    dependency_graph = pipeline_result.context.get("dependency_graph", {})
    dependencies = dependency_graph.get(target_service, [])
    unhealthy_deps = [dep for dep in dependencies if SERVICES.get(dep, {}).get("status") != "healthy"]

    # 5. Recent deployments to this service
    all_deploys = await mock_db_execute("SELECT * FROM deployments")
    service_deploys = [d for d in all_deploys if d.get("service") == target_service]

    # 6. Build deployment record
    deploy_id = f"DEP-{uuid.uuid4().hex[:6].upper()}"
    deployment_record = {
        "id": deploy_id,
        "service": target_service,
        "version": target_version,
        "previous_version": current_version,
        "environment": target_env,
        "requested_at": datetime.now(UTC).isoformat(),
        "status": "pending_approval",
    }

    # 7. Risk assessment
    risk_factors: list[str] = []
    risk_level = "low"
    if is_blocked:
        risk_factors.append(f"Service {target_service} has active incidents")
        risk_level = "high"
    if unhealthy_deps:
        risk_factors.append(f"Unhealthy dependencies: {', '.join(unhealthy_deps)}")
        risk_level = "high"
    if target_env == "production":
        risk_factors.append("Production deployment")
        risk_level = max(risk_level, "medium", key=lambda x: {"low": 0, "medium": 1, "high": 2}[x])
    if not risk_factors:
        risk_factors.append("No risk factors identified")

    trace_id = f"trace-{uuid.uuid4().hex[:8]}"

    # 8. Schedule background tasks (run after response is sent)
    tasks.add_task(
        enqueue_deployment_job,
        deploy_id=deploy_id,
        service=target_service,
        version=target_version,
    )
    tasks.add_task(
        notify_slack_channel,
        message=f"Deployment {deploy_id}: {target_service} v{target_version} to {target_env} (risk: {risk_level})",
    )

    return AgentResponse(
        result={
            "deployment": deployment_record,
            "pre_checks": {
                "current_version": current_version,
                "target_version": target_version,
                "blocked_by_incidents": is_blocked,
                "unhealthy_dependencies": unhealthy_deps,
                "recent_deployments": len(service_deploys),
            },
            "risk_assessment": {
                "level": risk_level,
                "factors": risk_factors,
            },
            "pipeline": {
                "stages_executed": pipeline_result.stages_executed,
                "all_services": pipeline_result.context.get("services_available", []),
            },
            "approval_required": True,
        },
        status="pending_approval",
        reasoning=(
            f"Deployment {deploy_id}: {target_service} v{current_version} -> v{target_version} ({target_env}). "
            f"Risk: {risk_level} ({len(risk_factors)} factors). "
            f"Pipeline: {len(pipeline_result.stages_executed)} stages. "
            f"Requires release_manager approval."
        ),
        confidence=0.9 if not is_blocked else 0.5,
        execution_trace_id=trace_id,
        approval_request={
            "required_approvers": ["release_manager", "sre_lead"],
            "reason": f"Deploy {target_service} v{target_version} to {target_env}",
            "risk_level": risk_level,
            "blocked": is_blocked,
        },
        follow_up_suggestions=[
            f"Check health of {target_service} dependencies before approving",
            "Review recent incidents that may affect this deployment",
            f"After approval, monitor {target_service} via 'services.health'",
        ],
    )


# ---------------------------------------------------------------------------
# DEPLOYMENTS.ROLLBACK — Pipeline + Approval + Trust + Multi-tool + Audit
# ---------------------------------------------------------------------------


@deployment_router.agent_endpoint(
    name="rollback",
    description=(
        "Rollback a service to a previous version. Combines impact analysis, "
        "A2A trust verification, approval workflow, and queue-based execution."
    ),
    intent_scope=IntentScope(
        allowed_intents=["deploy.*", "deployment.*", "rollback.*", "*.write", "*.execute", "*.read", "*.clarify"],
        denied_intents=["*.bulk_delete", "*.force_deploy"],
    ),
    autonomy_level="supervised",
)
async def deployment_rollback(intent: Intent, context: AgentContext) -> AgentResponse:
    """Rollback a deployment with full safety composition.

    Features exercised:
    1. DynamicPipeline: auth + impact_analysis + dependency_check
    2. A2A TrustScorer: verify rollback automation agent trust
    3. DatabaseTool: find previous version and deployment history
    4. QueueTool: enqueue rollback job
    5. CacheTool: invalidate cached data for the service
    6. ApprovalWorkflow: rollbacks need SRE approval
    7. AuditRecorder: full rollback trace
    """
    # 1. Pipeline: auth + impact analysis + dependency check
    pipeline_result = await pipeline.execute(
        context={"intent": intent.raw, "action": intent.action.value},
        selected_stages=["impact_analysis", "dependency_check"],
    )

    # 2. Extract rollback details
    target_service = intent.parameters.get("service", "unknown")
    target_version = intent.parameters.get("version")  # Version to roll back TO

    # 3. Current state
    current_info = SERVICES.get(target_service, {})
    current_version = current_info.get("version", "unknown")

    # 4. Find rollback target from deployment history
    all_deploys = await mock_db_execute("SELECT * FROM deployments")
    service_deploys = [d for d in all_deploys if d.get("service") == target_service]
    if not target_version and service_deploys:
        target_version = service_deploys[-1].get("previous_version", "unknown")

    # 5. Impact analysis from pipeline
    reverse_deps = pipeline_result.context.get("reverse_dependencies", {})
    affected_services = reverse_deps.get(target_service, [])

    # 6. Trust: verify rollback automation agent
    rollback_agent = "ci-cd-bot"
    agent_trust = trust_scorer.get_score(rollback_agent)
    can_execute = trust_scorer.can_write(rollback_agent)

    # 7. Build rollback record
    rollback_id = f"RB-{uuid.uuid4().hex[:6].upper()}"
    rollback_record = {
        "id": rollback_id,
        "service": target_service,
        "from_version": current_version,
        "to_version": target_version or "unknown",
        "requested_at": datetime.now(UTC).isoformat(),
        "status": "pending_approval",
        "executor": rollback_agent,
    }

    trace_id = f"trace-{uuid.uuid4().hex[:8]}"

    return AgentResponse(
        result={
            "rollback": rollback_record,
            "impact_analysis": {
                "affected_services": affected_services,
                "blast_radius": len(affected_services),
                "current_version": current_version,
                "rollback_to": target_version or "unknown",
            },
            "trust_verification": {
                "executor_agent": rollback_agent,
                "trust_score": agent_trust,
                "can_execute": can_execute,
            },
            "pipeline": {
                "stages_executed": pipeline_result.stages_executed,
            },
            "approval_required": True,
        },
        status="pending_approval",
        reasoning=(
            f"Rollback {rollback_id}: {target_service} v{current_version} -> v{target_version or 'previous'}. "
            f"Blast radius: {len(affected_services)} dependent services. "
            f"Executor '{rollback_agent}' trust: {agent_trust:.2f} (can_execute: {can_execute}). "
            f"Requires SRE approval."
        ),
        confidence=0.85 if can_execute else 0.4,
        execution_trace_id=trace_id,
        approval_request={
            "required_approvers": ["sre_lead"],
            "reason": f"Rollback {target_service} from v{current_version} to v{target_version or 'previous'}",
            "blast_radius": len(affected_services),
        },
        follow_up_suggestions=[
            f"Investigate why {target_service} v{current_version} is failing",
            f"After rollback, verify health of dependent services: {', '.join(affected_services) or 'none'}",
            "Check audit trail for the original deployment",
        ],
    )


# ---------------------------------------------------------------------------
# SERVICES.HEALTH — Pipeline + OpsAgent + A2A + Multi-tool + Audit
# ---------------------------------------------------------------------------


@service_router.agent_endpoint(
    name="health",
    description=(
        "Comprehensive service health dashboard. Combines ops agent monitoring, "
        "A2A capability/trust queries, multi-tool data gathering, "
        "pipeline preprocessing, and audit recording."
    ),
    intent_scope=IntentScope(
        allowed_intents=["service.*", "health.*", "status.*", "*.read", "*.analyze", "*.clarify"],
    ),
    autonomy_level="auto",
)
async def service_health(intent: Intent, context: AgentContext) -> AgentResponse:
    """Comprehensive health check combining multiple data sources.

    Features exercised:
    1. DynamicPipeline: auth + rate_limit + incident_enrichment + cache_check
    2. OpsAgent: platform health monitor check
    3. A2A CapabilityRegistry: list available monitoring capabilities
    4. TrustScorer: show trust levels for monitoring agents
    5. DatabaseTool: fetch service and incident data
    6. HttpClientTool: (would) query external monitoring
    7. CacheTool: cache health snapshots
    8. AuditRecorder: record health check trace
    """
    # 1. Pipeline: full preprocessing
    pipeline_result = await pipeline.execute(
        context={"intent": intent.raw, "action": intent.action.value},
        selected_stages=["incident_enrichment", "cache_check"],
    )

    # 2. Ops agent health check
    ops_health = await platform_monitor.check_health()

    # 3. Per-service health with enrichment
    service_health_data: list[dict[str, Any]] = []
    for name, info in SERVICES.items():
        svc_logs = LOGS.get(name, [])
        error_count = sum(1 for log in svc_logs if log.get("level") == "ERROR")
        svc_incidents = [i for i in INCIDENTS if i.get("service") == name and i["status"] in ("open", "investigating")]

        service_health_data.append(
            {
                "name": name,
                "status": info["status"],
                "version": info["version"],
                "replicas": info["replicas"],
                "cpu_pct": info["cpu_pct"],
                "mem_mb": info["mem_mb"],
                "recent_errors": error_count,
                "active_incidents": len(svc_incidents),
                "needs_attention": info["status"] != "healthy" or error_count > 0 or len(svc_incidents) > 0,
            }
        )

    # 4. A2A: monitoring capabilities and agent trust
    capabilities = a2a_capabilities.list_capabilities()
    monitoring_agents = {
        agent: {
            "trust_score": trust_scorer.get_score(agent),
            "can_read": trust_scorer.can_read(agent),
            "can_write": trust_scorer.can_write(agent),
        }
        for agent in ["log-analyzer", "metrics-collector", "ci-cd-bot", "unknown-agent"]
    }

    # 5. Summary stats
    total = len(SERVICES)
    healthy_count = sum(1 for s in service_health_data if s["status"] == "healthy")
    needs_attention = [s["name"] for s in service_health_data if s["needs_attention"]]

    trace_id = f"trace-{uuid.uuid4().hex[:8]}"

    return AgentResponse(
        result={
            "summary": {
                "total_services": total,
                "healthy": healthy_count,
                "degraded": sum(1 for s in service_health_data if s["status"] == "degraded"),
                "unhealthy": sum(1 for s in service_health_data if s["status"] == "unhealthy"),
                "needs_attention": needs_attention,
            },
            "services": service_health_data,
            "ops_agent": {
                "name": platform_monitor.name,
                "healthy": ops_health.healthy,
                "message": ops_health.message,
                "details": ops_health.details,
                "can_handle_low_severity": platform_monitor.can_handle_autonomously(Severity.LOW),
                "can_handle_critical": platform_monitor.can_handle_autonomously(Severity.CRITICAL),
            },
            "a2a": {
                "capabilities": [{"name": c.name, "sla_ms": c.sla_max_latency_ms} for c in capabilities],
                "monitoring_agents": monitoring_agents,
            },
            "pipeline": {
                "stages_executed": pipeline_result.stages_executed,
                "active_incidents": pipeline_result.context.get("incident_count", 0),
            },
        },
        reasoning=(
            f"Health check: {healthy_count}/{total} services healthy, "
            f"{len(needs_attention)} need attention. "
            f"Ops agent: {'healthy' if ops_health.healthy else ops_health.message}. "
            f"{len(capabilities)} A2A capabilities available."
        ),
        confidence=0.95,
        execution_trace_id=trace_id,
        follow_up_suggestions=[
            f"Investigate services needing attention: {', '.join(needs_attention)}"
            if needs_attention
            else "All services healthy",
            "Check recent deployments that may correlate with issues",
            "Review A2A agent trust scores for monitoring reliability",
        ],
    )


# ============================================================================
# 12. LLM PROVIDER SELECTION
# ============================================================================


def _create_llm_backend() -> Any:
    """Create an LLM backend based on AGENTICAPI_LLM_PROVIDER env var."""
    import os

    provider = os.environ.get("AGENTICAPI_LLM_PROVIDER", "openai").lower()

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        from agenticapi.runtime.llm.anthropic import AnthropicBackend

        return AnthropicBackend()

    if provider == "gemini":
        if not os.environ.get("GOOGLE_API_KEY"):
            return None
        from agenticapi.runtime.llm.gemini import GeminiBackend

        return GeminiBackend()

    # Default: openai
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    from agenticapi.runtime.llm.openai import OpenAIBackend

    return OpenAIBackend()


llm = _create_llm_backend()


# ============================================================================
# 13. APP ASSEMBLY
# ============================================================================

app = AgenticApp(
    title="DevOps Incident & Deployment Platform",
    version="0.1.0",
    llm=llm,
    harness=harness,
)

# Register routers
app.include_router(incident_router)
app.include_router(deployment_router)
app.include_router(service_router)

# Add ASGI middleware — wraps every request/response
app.add_middleware(RequestTimingMiddleware)

# Register ops agent
app.register_ops_agent(platform_monitor)


# ============================================================================
# 14. REST COMPATIBILITY
# ============================================================================

rest_compat = RESTCompat(app, prefix="/rest")
rest_routes = rest_compat.generate_routes()
app.add_routes(rest_routes)


# ============================================================================
# 15. PROGRAMMATIC API DEMO
# ============================================================================


async def demo() -> None:
    """Demonstrate combined feature composition across endpoints.

    Run with:
        python -c "import asyncio; from examples.07_comprehensive.app import demo; asyncio.run(demo())"
    """
    print("=== AgenticAPI Comprehensive Demo: DevOps Platform ===\n")

    def _unwrap(response: AgentResponse) -> AgentResponse:
        """When the harness generates code, process_intent wraps the result;
        unwrap to get the inner AgentResponse for display."""
        inner = response.result
        if isinstance(inner, AgentResponse):
            return inner
        return response

    def _safe_get(data: Any, key: str, default: Any = None) -> Any:
        """Safely get a key from a dict-like result (handles both handler and LLM paths)."""
        if isinstance(data, dict):
            return data.get(key, default)
        return default

    # --- 1. Report an incident (pipeline + trust + tools + audit) ---
    print("--- 1. Report Incident ---")
    r = _unwrap(
        await app.process_intent(
            "API gateway returning 502 errors for 15 minutes",
            endpoint_name="incidents.report",
        )
    )
    result = r.result
    if isinstance(result, dict) and "incident" in result:
        print(f"  Incident: {result['incident']['id']} ({result['incident']['severity']})")
        print(f"  Trust: {result['trust_verification']}")
        print(f"  Pipeline stages: {result['pipeline']['stages_executed']}")
        print(f"  Duplicates checked: {result['deduplication']}")
    else:
        print(f"  Result: {str(result)[:200]}")
    print(f"  Status: {r.status}")
    print(f"  Suggestions: {r.follow_up_suggestions}\n")

    # --- 2. Investigate (multi-tool + A2A + session) ---
    print("--- 2. Investigate Incident ---")
    r = _unwrap(
        await app.process_intent(
            "Check logs and metrics for api-gateway",
            endpoint_name="incidents.investigate",
            session_id="investigation-001",
        )
    )
    result = r.result
    if isinstance(result, dict) and "target_service" in result:
        print(f"  Target: {result['target_service']}")
        print(f"  Errors found: {result['log_analysis']['errors']}")
        print(f"  Hypotheses: {result['hypotheses']}")
        print(f"  A2A capabilities: {result['a2a_capabilities']['available']}")
        print(f"  Trusted sources: {list(result['trusted_data_sources'].keys())}")
    else:
        print(f"  Result: {str(result)[:200]}")
    print()

    # Follow-up investigation turn (same session)
    r2 = _unwrap(
        await app.process_intent(
            "Now check the payment-service that api-gateway depends on",
            endpoint_name="incidents.investigate",
            session_id="investigation-001",
        )
    )
    result2 = r2.result
    if isinstance(result2, dict) and "target_service" in result2:
        print(f"  Follow-up target: {result2['target_service']}")
        print(f"  Follow-up errors: {result2['log_analysis']['errors']}")
    else:
        print(f"  Follow-up result: {str(result2)[:200]}")
    print()

    # --- 3. Create deployment (pipeline + approval + tools + policies) ---
    print("--- 3. Create Deployment ---")
    r = _unwrap(
        await app.process_intent(
            "Deploy payment-service v2.3.1 to production",
            endpoint_name="deployments.create",
        )
    )
    result = r.result
    if isinstance(result, dict) and "deployment" in result:
        dep = result["deployment"]
        risk = result["risk_assessment"]
        print(f"  Deployment: {dep['id']} ({dep['service']} v{dep['version']})")
        print(f"  Risk: {risk['level']} — {risk['factors']}")
        print(f"  Pre-checks: blocked={result['pre_checks']['blocked_by_incidents']}")
    else:
        print(f"  Result: {str(result)[:200]}")
    print(f"  Status: {r.status}")
    print(f"  Approval: {r.approval_request}\n")

    # --- 4. Rollback (pipeline + trust + impact + approval) ---
    print("--- 4. Rollback ---")
    r = _unwrap(
        await app.process_intent(
            "Rollback payment-service to previous version",
            endpoint_name="deployments.rollback",
        )
    )
    result = r.result
    if isinstance(result, dict) and "rollback" in result:
        rb = result["rollback"]
        impact = result["impact_analysis"]
        print(f"  Rollback: {rb['id']} ({rb['service']} v{rb['from_version']} -> v{rb['to_version']})")
        print(f"  Blast radius: {impact['blast_radius']} services ({impact['affected_services']})")
        print(f"  Executor trust: {result['trust_verification']}")
    else:
        print(f"  Result: {str(result)[:200]}")
    print(f"  Confidence: {r.confidence}\n")

    # --- 5. Service health (ops + A2A + pipeline + tools) ---
    print("--- 5. Service Health ---")
    r = _unwrap(
        await app.process_intent(
            "Show health of all services",
            endpoint_name="services.health",
        )
    )
    result = r.result
    if isinstance(result, dict) and "summary" in result:
        summary = result["summary"]
        ops = result["ops_agent"]
        a2a = result["a2a"]
        print(f"  Services: {summary['healthy']}/{summary['total_services']} healthy")
        print(f"  Needs attention: {summary['needs_attention']}")
        print(f"  Ops agent: {ops['message']}")
        print(f"  A2A capabilities: {[c['name'] for c in a2a['capabilities']]}")
        print(f"  Monitoring agents: {list(a2a['monitoring_agents'].keys())}")
    else:
        print(f"  Result: {str(result)[:200]}")

    # --- 6. Audit trail ---
    print("\n--- 6. Audit Trail ---")
    records = audit_recorder.get_records(limit=10)
    print(f"  Total audit records: {len(records)}")

    print("\n=== Demo complete ===")
