"""Full-stack AgenticAPI example: every major feature in one app.

Demonstrates:
- AgenticApp with HarnessEngine, policies, approval, sandbox monitors/validators
- Starlette middleware (CORS, request timing)
- AgentTasks for background tasks (notification after shipment creation)
- File upload (multipart/form-data with UploadedFiles injection)
- File download (FileResult for CSV export)
- DynamicPipeline for request preprocessing (middleware-like stages)
- OpsAgent for autonomous operational monitoring
- A2A CapabilityRegistry and TrustScorer for inter-agent trust
- REST compatibility layer (expose agent endpoints as GET/POST)
- All four policy types: CodePolicy, DataPolicy, ResourcePolicy, RuntimePolicy
- All four tool types: DatabaseTool, CacheTool, HttpClientTool, QueueTool
- Sandbox ResourceMonitor and OutputSizeMonitor
- OutputTypeValidator and ReadOnlyValidator
- AuditRecorder with ConsoleExporter
- IntentScope with allow/deny patterns
- SessionManager (multi-turn via session_id)
- process_intent() programmatic API
- Multiple AgentRouters with prefix/tags

LLM provider selection (via AGENTICAPI_LLM_PROVIDER env var):
    export AGENTICAPI_LLM_PROVIDER=openai    # default — requires OPENAI_API_KEY
    export AGENTICAPI_LLM_PROVIDER=anthropic  # requires ANTHROPIC_API_KEY
    export AGENTICAPI_LLM_PROVIDER=gemini     # requires GOOGLE_API_KEY

    If the chosen provider's API key is not set, the app still starts
    but falls back to direct handler invocation (no code generation).

Run with:
    uvicorn examples.06_full_stack.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.06_full_stack.app:app

Test with curl:
    # --- Inventory queries ---
    curl -X POST http://127.0.0.1:8000/agent/inventory.query \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show all items in the Tokyo warehouse"}'

    # --- Inventory analytics ---
    curl -X POST http://127.0.0.1:8000/agent/inventory.analytics \
        -H "Content-Type: application/json" \
        -d '{"intent": "Compare stock levels across warehouses"}'

    # --- Shipment creation (triggers approval) ---
    curl -X POST http://127.0.0.1:8000/agent/shipping.create \
        -H "Content-Type: application/json" \
        -d '{"intent": "Ship 50 units of Laptop from Tokyo to Osaka"}'

    # --- Shipment tracking ---
    curl -X POST http://127.0.0.1:8000/agent/shipping.track \
        -H "Content-Type: application/json" \
        -d '{"intent": "Where is shipment SHP-001?"}'

    # --- Multi-turn session ---
    curl -X POST http://127.0.0.1:8000/agent/inventory.query \
        -H "Content-Type: application/json" \
        -d '{"intent": "Show Tokyo warehouse", "session_id": "demo-session"}'

    curl -X POST http://127.0.0.1:8000/agent/inventory.query \
        -H "Content-Type: application/json" \
        -d '{"intent": "Which of those are low in stock?", "session_id": "demo-session"}'

    # --- REST compatibility ---
    curl "http://127.0.0.1:8000/rest/inventory.query?query=show+all+items"
    curl -X POST http://127.0.0.1:8000/rest/inventory.query \
        -H "Content-Type: application/json" \
        -d '{"query": "add 100 units of Monitor"}'

    # --- File upload ---
    curl -X POST http://127.0.0.1:8000/agent/files.upload \
        -F 'intent=Analyze this inventory report' \
        -F 'document=@report.csv'

    # --- File download (CSV export) ---
    curl -X POST http://127.0.0.1:8000/agent/files.export \
        -H "Content-Type: application/json" \
        -d '{"intent": "Export inventory as CSV"}' -o inventory.csv

    # --- Health check (includes ops agent status) ---
    curl http://127.0.0.1:8000/health

    # --- Programmatic usage (Python) ---
    # from examples.06_full_stack.app import app
    # response = await app.process_intent("Show all low-stock items")
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

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
from agenticapi.interface.response import AgentResponse, FileResult
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
    from agenticapi.interface.upload import UploadedFiles
    from agenticapi.runtime.context import AgentContext


# ============================================================================
# 1. MOCK DATA — multi-warehouse inventory and shipment tracker
# ============================================================================

WAREHOUSES = {
    "tokyo": [
        {"sku": "LAPTOP-001", "name": "Laptop Pro 15", "category": "electronics", "stock": 120, "price": 148000},
        {"sku": "MOUSE-001", "name": "Ergonomic Mouse", "category": "electronics", "stock": 500, "price": 8900},
        {"sku": "DESK-001", "name": "Standing Desk", "category": "furniture", "stock": 5, "price": 62000},
        {"sku": "CHAIR-001", "name": "Office Chair", "category": "furniture", "stock": 18, "price": 45000},
        {"sku": "BOOK-001", "name": "Python in Action", "category": "books", "stock": 300, "price": 3800},
    ],
    "osaka": [
        {"sku": "LAPTOP-001", "name": "Laptop Pro 15", "category": "electronics", "stock": 80, "price": 148000},
        {"sku": "MONITOR-001", "name": "4K Monitor", "category": "electronics", "stock": 45, "price": 54000},
        {"sku": "DESK-001", "name": "Standing Desk", "category": "furniture", "stock": 12, "price": 62000},
        {"sku": "HEADSET-001", "name": "Noise-Cancel Headset", "category": "electronics", "stock": 200, "price": 28000},
    ],
    "fukuoka": [
        {"sku": "MOUSE-001", "name": "Ergonomic Mouse", "category": "electronics", "stock": 150, "price": 8900},
        {"sku": "BOOK-001", "name": "Python in Action", "category": "books", "stock": 80, "price": 3800},
        {"sku": "BOOK-002", "name": "Go Concurrency", "category": "books", "stock": 60, "price": 4200},
    ],
}

SHIPMENTS = [
    {"id": "SHP-001", "from": "tokyo", "to": "osaka", "sku": "LAPTOP-001", "qty": 20, "status": "in_transit"},
    {"id": "SHP-002", "from": "osaka", "to": "fukuoka", "sku": "MONITOR-001", "qty": 10, "status": "delivered"},
    {"id": "SHP-003", "from": "fukuoka", "to": "tokyo", "sku": "BOOK-001", "qty": 50, "status": "pending"},
]

LOW_STOCK_THRESHOLD = 10


async def mock_db_execute(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Simulate database queries across warehouses and shipments."""
    q = query.lower()
    if "shipment" in q or "shipping" in q:
        return SHIPMENTS
    # Return flattened inventory with warehouse tag
    all_items: list[dict[str, Any]] = []
    for warehouse, items in WAREHOUSES.items():
        for item in items:
            all_items.append({**item, "warehouse": warehouse})
    return all_items


# ============================================================================
# 2. TOOLS — all four built-in types
# ============================================================================

db_tool = DatabaseTool(
    name="warehouse_db",
    description=(
        "Multi-warehouse inventory database. "
        "Tables: inventory (sku, name, category, stock, price, warehouse), "
        "shipments (id, from, to, sku, qty, status)."
    ),
    execute_fn=mock_db_execute,
    read_only=True,
)

cache_tool = CacheTool(
    name="inventory_cache",
    description="Cache for inventory queries and analytics results",
    default_ttl_seconds=60,
    max_size=500,
)

http_tool = HttpClientTool(
    name="logistics_api",
    description="External logistics partner API for shipping rate quotes",
    allowed_hosts=["api.logistics.example.com"],
    timeout=10.0,
)

queue_tool = QueueTool(
    name="shipment_queue",
    description="Async queue for shipment processing jobs",
    max_size=1000,
)

tools = ToolRegistry()
tools.register(db_tool)
tools.register(cache_tool)
tools.register(http_tool)
tools.register(queue_tool)


# ============================================================================
# 3. POLICIES — all four policy types
# ============================================================================

code_policy = CodePolicy(
    denied_modules=["os", "subprocess", "shutil", "sys", "importlib", "pathlib", "ctypes"],
    deny_eval_exec=True,
    deny_dynamic_import=True,
    allow_network=False,
    max_code_lines=300,
)

data_policy = DataPolicy(
    readable_tables=["inventory", "shipments", "warehouses"],
    writable_tables=["shipments"],
    restricted_columns=["cost_price", "supplier_contact", "internal_notes"],
    deny_ddl=True,
    max_result_rows=2000,
)

resource_policy = ResourcePolicy(
    max_cpu_seconds=15,
    max_memory_mb=256,
    max_execution_time_seconds=30,
    max_concurrent_operations=5,
)

runtime_policy = RuntimePolicy(
    max_code_complexity=500,
    max_code_lines=300,
)


# ============================================================================
# 4. APPROVAL WORKFLOW — write operations need a logistics manager
# ============================================================================

approval_workflow = ApprovalWorkflow(
    rules=[
        ApprovalRule(
            name="shipment_approval",
            require_for_actions=["write", "execute"],
            require_for_domains=["shipping", "shipment"],
            approvers=["logistics_manager", "warehouse_lead"],
            timeout_seconds=3600,
        ),
    ],
)


# ============================================================================
# 5. SANDBOX MONITORS & VALIDATORS
# ============================================================================

resource_limits = ResourceLimits(
    max_cpu_seconds=15,
    max_memory_mb=256,
    max_execution_time_seconds=30,
)

monitors = [
    ResourceMonitor(limits=resource_limits),
    OutputSizeMonitor(max_output_bytes=500_000),
]

validators = [
    OutputTypeValidator(),
    ReadOnlyValidator(),
]


# ============================================================================
# 6. AUDIT — trace every execution
# ============================================================================

audit_recorder = AuditRecorder(max_traces=5000)
console_exporter = ConsoleExporter()  # prints traces to stdout in dev


# ============================================================================
# 7. HARNESS ENGINE — wires everything together
# ============================================================================

harness = HarnessEngine(
    policies=[code_policy, data_policy, resource_policy, runtime_policy],
    audit_recorder=audit_recorder,
    approval_workflow=approval_workflow,
    monitors=monitors,
    validators=validators,
)


# ============================================================================
# 8. DYNAMIC PIPELINE — preprocessing stages
# ============================================================================


def auth_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Simulate authentication — tag the request with a user."""
    ctx["authenticated_user"] = ctx.get("user", "anonymous")
    ctx["user_role"] = "operator"
    return ctx


def rate_limit_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Simulate rate limiting — mark request as within limits."""
    ctx["rate_limited"] = False
    return ctx


def warehouse_context_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Enrich context with available warehouse names."""
    ctx["available_warehouses"] = list(WAREHOUSES.keys())
    return ctx


def cache_check_stage(ctx: dict[str, Any]) -> dict[str, Any]:
    """Simulate a cache check for read-heavy requests."""
    ctx["cache_hit"] = False
    return ctx


pipeline = DynamicPipeline(
    base_stages=[
        PipelineStage("auth", description="Authentication", handler=auth_stage, required=True, order=10),
        PipelineStage("rate_limit", description="Rate limiting", handler=rate_limit_stage, required=True, order=20),
    ],
    available_stages=[
        PipelineStage(
            "warehouse_ctx",
            description="Add warehouse context for inventory queries",
            handler=warehouse_context_stage,
            order=30,
        ),
        PipelineStage(
            "cache_check",
            description="Cache check for read queries",
            handler=cache_check_stage,
            order=25,
        ),
    ],
    max_stages=8,
)


# ============================================================================
# 9. A2A — capability registry and trust scoring
# ============================================================================

a2a_capabilities = CapabilityRegistry()
a2a_capabilities.register(
    Capability(
        name="inventory_lookup",
        description="Look up inventory levels across all warehouses",
        input_schema={"type": "object", "properties": {"sku": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"stock": {"type": "integer"}}},
        sla_max_latency_ms=200,
        sla_availability=0.999,
    )
)
a2a_capabilities.register(
    Capability(
        name="shipping_estimate",
        description="Estimate shipping cost and time between warehouses",
        input_schema={"type": "object", "properties": {"from": {"type": "string"}, "to": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"cost_yen": {"type": "integer"}, "days": {"type": "integer"}}},
        sla_max_latency_ms=500,
        sla_availability=0.99,
    )
)

trust_scorer = TrustScorer(
    policy=TrustPolicy(
        initial_trust=0.5,
        min_trust_for_read=0.3,
        min_trust_for_write=0.8,
        decay_per_failure=0.1,
        gain_per_success=0.05,
    )
)


# ============================================================================
# 10. OPS AGENT — inventory monitoring
# ============================================================================


class InventoryMonitor(OpsAgent):
    """Ops agent that monitors warehouse inventory levels.

    Detects low-stock situations and can autonomously trigger
    restock alerts for low/medium severity, but escalates
    critical shortages to humans.
    """

    async def start(self) -> None:
        self._running = True
        self._alerts: list[dict[str, Any]] = []
        # In a real app, this would start a background task
        # scanning inventory on an interval.

    async def stop(self) -> None:
        self._running = False

    async def check_health(self) -> OpsHealthStatus:
        # Scan for low-stock items
        low_stock_items: list[dict[str, Any]] = []
        for warehouse, items in WAREHOUSES.items():
            for item in items:
                if item["stock"] < LOW_STOCK_THRESHOLD:
                    low_stock_items.append({**item, "warehouse": warehouse})

        return OpsHealthStatus(
            healthy=self._running and len(low_stock_items) == 0,
            message=f"{len(low_stock_items)} low-stock alerts" if low_stock_items else "All stock levels normal",
            details={"low_stock_items": low_stock_items},
        )


inventory_monitor = InventoryMonitor(
    name="inventory-monitor",
    autonomy=AutonomyLevel.SUPERVISED,
    max_severity=Severity.MEDIUM,
)


# ============================================================================
# 11. ROUTERS AND ENDPOINTS
# ============================================================================

inventory_router = AgentRouter(prefix="inventory", tags=["inventory"])
shipping_router = AgentRouter(prefix="shipping", tags=["shipping"])


@inventory_router.agent_endpoint(
    name="query",
    description="Query inventory: list items, filter by warehouse/category/SKU, find low-stock items",
    intent_scope=IntentScope(
        allowed_intents=["inventory.*", "warehouse.*", "stock.*", "*.read", "*.analyze", "*.clarify"],
    ),
    autonomy_level="auto",
)
async def inventory_query(intent: Intent, context: AgentContext) -> AgentResponse:
    """Handle inventory read queries with dynamic pipeline preprocessing."""
    # Run the pipeline for request enrichment
    pipeline_result = await pipeline.execute(
        context={"intent": intent.raw, "action": intent.action.value},
        selected_stages=["warehouse_ctx", "cache_check"],
    )

    warehouse_filter = intent.parameters.get("warehouse")
    category_filter = intent.parameters.get("category")

    all_items: list[dict[str, Any]] = []
    for warehouse, items in WAREHOUSES.items():
        if warehouse_filter and warehouse != warehouse_filter.lower():
            continue
        for item in items:
            if category_filter and item["category"] != category_filter.lower():
                continue
            all_items.append({**item, "warehouse": warehouse})

    low_stock = [i for i in all_items if i["stock"] < LOW_STOCK_THRESHOLD]

    return AgentResponse(
        result={
            "items": all_items,
            "count": len(all_items),
            "low_stock": low_stock,
            "pipeline_stages": pipeline_result.stages_executed,
        },
        reasoning=(
            f"Queried {len(all_items)} items across {len(WAREHOUSES)} warehouses, {len(low_stock)} low-stock alerts"
        ),
    )


@inventory_router.agent_endpoint(
    name="analytics",
    description="Inventory analytics: stock comparisons across warehouses, category breakdowns, value analysis",
    intent_scope=IntentScope(
        allowed_intents=["inventory.*", "warehouse.*", "stock.*", "*.read", "*.analyze", "*.clarify"],
    ),
    autonomy_level="auto",
)
async def inventory_analytics(intent: Intent, context: AgentContext) -> AgentResponse:
    """Compute analytics across all warehouses."""
    by_warehouse: dict[str, dict[str, Any]] = {}
    for warehouse, items in WAREHOUSES.items():
        total_stock = sum(i["stock"] for i in items)
        total_value = sum(i["stock"] * i["price"] for i in items)
        low_stock_count = sum(1 for i in items if i["stock"] < LOW_STOCK_THRESHOLD)
        by_warehouse[warehouse] = {
            "item_count": len(items),
            "total_stock": total_stock,
            "total_value_yen": total_value,
            "low_stock_alerts": low_stock_count,
        }

    by_category: dict[str, dict[str, int]] = {}
    for items in WAREHOUSES.values():
        for item in items:
            cat = item["category"]
            by_category.setdefault(cat, {"total_stock": 0, "total_value_yen": 0, "sku_count": 0})
            by_category[cat]["total_stock"] += item["stock"]
            by_category[cat]["total_value_yen"] += item["stock"] * item["price"]
            by_category[cat]["sku_count"] += 1

    grand_total_stock = sum(w["total_stock"] for w in by_warehouse.values())
    grand_total_value = sum(w["total_value_yen"] for w in by_warehouse.values())

    return AgentResponse(
        result={
            "summary": {
                "warehouses": len(WAREHOUSES),
                "total_stock_units": grand_total_stock,
                "total_inventory_value_yen": grand_total_value,
            },
            "by_warehouse": by_warehouse,
            "by_category": by_category,
        },
        reasoning=(
            f"Analytics across {len(WAREHOUSES)} warehouses: "
            f"{grand_total_stock} units, {grand_total_value:,} yen total value"
        ),
    )


@shipping_router.agent_endpoint(
    name="track",
    description="Track shipments between warehouses, check delivery status",
    intent_scope=IntentScope(
        allowed_intents=["shipping.*", "shipment.*", "delivery.*", "*.read", "*.analyze", "*.clarify"],
    ),
    autonomy_level="auto",
)
async def shipment_track(intent: Intent, context: AgentContext) -> AgentResponse:
    """Track shipment status."""
    shipment_id = intent.parameters.get("shipment_id")
    status_filter = intent.parameters.get("status")

    results = SHIPMENTS
    if shipment_id:
        results = [s for s in results if s["id"] == shipment_id]
    if status_filter:
        results = [s for s in results if s["status"] == status_filter]

    return AgentResponse(
        result={"shipments": results, "count": len(results)},
        reasoning=f"Found {len(results)} shipments matching the query",
    )


@shipping_router.agent_endpoint(
    name="create",
    description="Create new shipments between warehouses (requires approval)",
    intent_scope=IntentScope(
        allowed_intents=["shipping.*", "shipment.*", "*.write", "*.execute", "*.read", "*.clarify"],
        denied_intents=["*.bulk_delete"],
    ),
    autonomy_level="supervised",
)
async def shipment_create(intent: Intent, context: AgentContext, tasks: AgentTasks) -> AgentResponse:
    """Handle shipment creation with background notification tasks."""
    # Schedule background tasks that run after the response is sent
    tasks.add_task(_notify_logistics, intent_raw=intent.raw, trace_id=context.trace_id)
    tasks.add_task(_log_shipment_request, intent_raw=intent.raw)

    return AgentResponse(
        result={
            "message": f"Shipment creation requested: {intent.raw}",
            "approval_required": True,
            "required_approvers": ["logistics_manager", "warehouse_lead"],
            "background_tasks_scheduled": tasks.pending_count,
        },
        status="pending_review",
        reasoning="Write operations on shipments require logistics manager approval per policy",
    )


# ============================================================================
# 12. FILE HANDLING ENDPOINTS — upload and download
# ============================================================================

files_router = AgentRouter(prefix="files", tags=["files"])


@files_router.agent_endpoint(
    name="upload",
    description="Upload inventory documents (CSV, PDF) for analysis",
    intent_scope=IntentScope(
        allowed_intents=["*"],
    ),
    autonomy_level="auto",
)
async def file_upload(intent: Intent, context: AgentContext, files: UploadedFiles) -> dict[str, Any]:
    """Accept uploaded files and return metadata.

    Upload via multipart/form-data:
        curl -F 'intent=Analyze this' -F 'document=@report.csv' /agent/files.upload
    """
    if not files:
        return {"message": "No files uploaded", "hint": "Use multipart/form-data with a file field"}

    file_info: list[dict[str, Any]] = []
    for field_name, upload in files.items():
        file_info.append(
            {
                "field": field_name,
                "filename": upload.filename,
                "content_type": upload.content_type,
                "size_bytes": upload.size,
            }
        )

    return {
        "message": f"Received {len(files)} file(s)",
        "files": file_info,
        "intent": intent.raw,
    }


@files_router.agent_endpoint(
    name="export",
    description="Export inventory data as CSV download",
    intent_scope=IntentScope(
        allowed_intents=["*"],
    ),
    autonomy_level="auto",
)
async def file_export(intent: Intent, context: AgentContext) -> FileResult:
    """Generate a CSV export of all warehouse inventory.

    Returns a downloadable CSV file.
    """
    lines: list[str] = ["warehouse,sku,name,category,stock,price"]
    for warehouse, items in WAREHOUSES.items():
        for item in items:
            lines.append(f"{warehouse},{item['sku']},{item['name']},{item['category']},{item['stock']},{item['price']}")

    csv_content = "\n".join(lines)
    return FileResult(
        content=csv_content.encode("utf-8"),
        media_type="text/csv",
        filename="inventory_export.csv",
    )


# ============================================================================
# 13. BACKGROUND TASK FUNCTIONS
# ============================================================================
# These run after the response is sent, triggered by AgentTasks.add_task().


async def _notify_logistics(*, intent_raw: str, trace_id: str) -> None:
    """Notify the logistics team about a shipment request.

    In production this would send a Slack message or email.
    """
    import structlog

    logger = structlog.get_logger("background")
    logger.info("logistics_notified", intent=intent_raw[:100], trace_id=trace_id)


def _log_shipment_request(*, intent_raw: str) -> None:
    """Log the shipment request for analytics (sync background task)."""
    import structlog

    logger = structlog.get_logger("background")
    logger.info("shipment_request_logged", intent=intent_raw[:100])


# ============================================================================
# 14. LLM PROVIDER SELECTION
# ============================================================================
# Set AGENTICAPI_LLM_PROVIDER to "openai" (default), "anthropic", or "gemini".
# The corresponding API key env var must also be set.
# If the key is missing the app starts in direct-handler mode (no code generation).


def _create_llm_backend() -> Any:
    """Create an LLM backend based on the AGENTICAPI_LLM_PROVIDER env var."""
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
# 15. APP ASSEMBLY — bring it all together
# ============================================================================

app = AgenticApp(
    title="Full-Stack Warehouse Agent",
    version="0.1.0",
    llm=llm,
    harness=harness,
)

# Register routers
app.include_router(inventory_router)
app.include_router(shipping_router)
app.include_router(files_router)

# Register ops agent
app.register_ops_agent(inventory_monitor)


# ============================================================================
# 16. MIDDLEWARE — CORS + request timing (ASGI-level, wraps all routes)
# ============================================================================

# CORS — allow cross-origin requests from any frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Custom request timing middleware — adds X-Process-Time header
class RequestTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Any, call_next: Any) -> Any:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        response.headers["X-Process-Time"] = f"{duration_ms:.1f}ms"
        return response


app.add_middleware(RequestTimingMiddleware)


# ============================================================================
# 18. REST COMPATIBILITY — expose endpoints as conventional REST
# ============================================================================

rest_compat = RESTCompat(app, prefix="/rest")
rest_routes = rest_compat.generate_routes()
app.add_routes(rest_routes)
# The generated routes provide:
#   GET  /rest/inventory.query?query=...   -> read intent
#   POST /rest/inventory.query             -> write intent from JSON body
#   GET  /rest/inventory.analytics?query=...
#   GET  /rest/shipping.track?query=...
#   POST /rest/shipping.create
# These supplement the native POST /agent/{name} endpoints.


# ============================================================================
# 19. PROGRAMMATIC API DEMO (for use in tests or scripts)
# ============================================================================


async def demo() -> None:
    """Demonstrate the programmatic process_intent() API.

    Run with:
        python -c "import asyncio; from examples.06_full_stack.app import demo; asyncio.run(demo())"
    """
    print("=== AgenticAPI Full-Stack Demo ===\n")

    def _unwrap(response: AgentResponse) -> AgentResponse:
        """When a handler returns AgentResponse, process_intent wraps it;
        unwrap to get the inner result for display."""
        inner = response.result
        if isinstance(inner, AgentResponse):
            return inner
        return response

    # Query inventory
    response = _unwrap(await app.process_intent("Show all items in the Tokyo warehouse"))
    print(f"Inventory query: {response.result['count']} items found")
    print(f"  Pipeline stages: {response.result.get('pipeline_stages', [])}")
    print(f"  Reasoning: {response.reasoning}\n")

    # Analytics
    response = _unwrap(
        await app.process_intent(
            "Compare stock levels across warehouses",
            endpoint_name="inventory.analytics",
        )
    )
    summary = response.result["summary"]
    print(f"Analytics: {summary['warehouses']} warehouses, {summary['total_stock_units']} total units")
    print(f"  Total value: {summary['total_inventory_value_yen']:,} yen\n")

    # Track shipments
    response = _unwrap(
        await app.process_intent(
            "Show all in-transit shipments",
            endpoint_name="shipping.track",
        )
    )
    print(f"Shipment tracking: {response.result['count']} shipments\n")

    # Multi-turn session
    r1 = _unwrap(await app.process_intent("Show Tokyo warehouse", session_id="demo"))
    r2 = _unwrap(await app.process_intent("Which of those are low in stock?", session_id="demo"))
    print(f"Session turn 1: {r1.result['count']} items")
    print(f"Session turn 2: {len(r2.result.get('low_stock', []))} low-stock items\n")

    # Ops agent health
    health = await inventory_monitor.check_health()
    print(f"Ops agent '{inventory_monitor.name}': healthy={health.healthy}, {health.message}")
    print(f"  Can handle LOW autonomously: {inventory_monitor.can_handle_autonomously(Severity.LOW)}")
    print(f"  Can handle CRITICAL autonomously: {inventory_monitor.can_handle_autonomously(Severity.CRITICAL)}\n")

    # A2A capabilities
    print(f"A2A capabilities registered: {[c.name for c in a2a_capabilities.list_capabilities()]}")
    print(f"Trust score for 'partner-agent': {trust_scorer.get_score('partner-agent')}")
    trust_scorer.record_success("partner-agent")
    print(f"After success: {trust_scorer.get_score('partner-agent')}")
    print(f"  Can read: {trust_scorer.can_read('partner-agent')}")
    print(f"  Can write: {trust_scorer.can_write('partner-agent')}\n")

    # Audit records
    records = audit_recorder.get_records(limit=5)
    print(f"Audit records: {len(records)} traces recorded")

    print("\n=== Demo complete ===")
