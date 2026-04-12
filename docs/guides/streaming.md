# Streaming

AgenticAPI endpoints can stream structured events to clients in real time instead of buffering the full response. Handlers emit typed events -- reasoning traces, tool-call progress, partial results, approval requests -- and the framework pushes each event through a transport (SSE or NDJSON) as it happens.

## Why streaming?

Agent endpoints often take seconds or minutes. Without streaming, the client stares at a spinner until the handler finishes. With streaming, the client sees the agent's chain of thought, tool activity, and partial results as they happen, and the user can intervene mid-execution via approval requests.

## AgentStream parameter injection

Declare an `AgentStream` parameter in your handler and set `streaming=` on the endpoint decorator. The framework injects a per-request stream instance and switches the response to the chosen transport.

```python
from agenticapi import AgenticApp, AgentStream, Intent
from agenticapi.runtime.context import AgentContext

app = AgenticApp(title="Streaming Demo")


@app.agent_endpoint(name="analyze", streaming="sse")
async def analyze(intent: Intent, context: AgentContext, stream: AgentStream):
    await stream.emit_thought("Reading the dataset...")
    data = await load_data(intent.raw)

    await stream.emit_thought("Running analysis...")
    for i, row in enumerate(data):
        result = process(row)
        await stream.emit_partial(result)

    return {"summary": "Analysis complete", "rows": len(data)}
```

The handler's return value is automatically wrapped in a terminal `FinalEvent` so the client always sees a clean end-of-stream marker.

## Event types

Every event is a Pydantic model with a `kind` discriminator, a monotonic `seq` number, and a UTC `timestamp`. The framework stamps `seq` and `timestamp` automatically -- handlers never set them.

| Event | `kind` | Purpose |
|---|---|---|
| `ThoughtEvent` | `thought` | Chain-of-thought reasoning chunk |
| `ToolCallStartedEvent` | `tool_call_started` | Tool invocation announced (with `call_id`, `name`, `arguments`) |
| `ToolCallCompletedEvent` | `tool_call_completed` | Tool invocation finished (with `call_id`, `is_error`, `duration_ms`) |
| `PartialResultEvent` | `partial_result` | Incremental result chunk for the client to append |
| `ApprovalRequestedEvent` | `approval_requested` | Handler paused, waiting for user decision |
| `ApprovalResolvedEvent` | `approval_resolved` | User answered the approval request |
| `AutonomyChangedEvent` | `autonomy_changed` | Live autonomy level escalated (see below) |
| `FinalEvent` | `final` | Terminal success event with the handler's return value |
| `ErrorEvent` | `error` | Terminal error event |

### Emit methods on AgentStream

```python
await stream.emit_thought("Thinking about the query...", confidence=0.85)

await stream.emit_tool_call_started(call_id="c1", name="db_query", arguments={"sql": "SELECT ..."})
await stream.emit_tool_call_completed(call_id="c1", result_summary="137 rows", duration_ms=42.0)

await stream.emit_partial({"row": 1, "value": 42})
await stream.emit_partial({"row": 2, "value": 99}, is_last=True)
```

## Transports: SSE vs NDJSON

The `streaming=` parameter on `@agent_endpoint` selects the wire format.

### SSE (`streaming="sse"`)

The default for browser clients. Each event is an SSE frame:

```
event: thought
data: {"kind":"thought","seq":0,"timestamp":"...","text":"Reading schema..."}

event: partial_result
data: {"kind":"partial_result","seq":1,"timestamp":"...","chunk":{"row":1}}
```

Browser clients consume this with `EventSource`. The transport emits `: keepalive` comment lines every 15 seconds to prevent reverse-proxy timeouts.

```bash
curl -N -X POST http://127.0.0.1:8000/agent/analyze \
    -H "Content-Type: application/json" \
    -d '{"intent": "Analyze Q1 sales data"}'
```

### NDJSON (`streaming="ndjson"`)

Better for CLI tools, `jq` pipelines, and non-browser clients. One JSON object per line:

```
{"kind":"thought","seq":0,"timestamp":"...","text":"Reading schema..."}
{"kind":"partial_result","seq":1,"timestamp":"...","chunk":{"row":1}}
```

Content-Type is `application/x-ndjson`. Heartbeats are bare newlines.

```bash
curl -N -X POST http://127.0.0.1:8000/agent/analyze \
    -H "Content-Type: application/json" \
    -d '{"intent": "Analyze Q1 sales data"}' | jq --unbuffered .
```

Both transports share the same event types, the same `AgentStream`, and the same audit integration. Only the wire rendering differs.

## In-stream approval requests

Handlers can pause mid-execution and ask the user a question via `stream.request_approval()`. The call emits an `ApprovalRequestedEvent` to the client, then suspends the handler coroutine until the framework receives a decision through the resume endpoint.

```python
@app.agent_endpoint(name="deploy", streaming="ndjson")
async def deploy(intent: Intent, context: AgentContext, stream: AgentStream):
    plan = build_deployment_plan(intent.raw)
    await stream.emit_thought(f"Deploying {plan.service} to {plan.target}...")

    if plan.is_production:
        decision = await stream.request_approval(
            prompt=f"Deploy {plan.service} v{plan.version} to production?",
            options=["approve", "reject", "add-canary"],
            timeout_seconds=300,
        )
        if decision == "reject":
            return {"status": "cancelled"}

    await execute_deployment(plan)
    return {"status": "deployed"}
```

The client sees the `approval_requested` event with an `approval_id` and `stream_id`, then POSTs the decision to the resume endpoint:

```bash
curl -X POST http://127.0.0.1:8000/agent/deploy/resume/<stream_id> \
    -H "Content-Type: application/json" \
    -d '{"approval_id": "<approval_id>", "decision": "approve"}'
```

If no decision arrives within `timeout_seconds`, the framework resolves with the configured default (typically `"reject"`).

## AutonomyPolicy and live escalation

An `AutonomyPolicy` lets you define rules that escalate the autonomy level of a running request based on live signals -- low confidence, high cost, policy flags. Attach it when constructing the app, and use `stream.report_signal()` to feed observations.

```python
from agenticapi import AutonomyPolicy, EscalateWhen

autonomy = AutonomyPolicy(
    default_level="auto",
    rules=[
        EscalateWhen(
            confidence_below=0.7,
            target="supervised",
            reason="Low confidence detected",
        ),
        EscalateWhen(
            cost_above_usd=0.50,
            target="manual",
            reason="Cost ceiling reached",
        ),
    ],
)

app = AgenticApp(title="Guarded Service", autonomy=autonomy)
```

Inside a streaming handler, report signals as they arise:

```python
@app.agent_endpoint(name="research", streaming="sse")
async def research(intent: Intent, stream: AgentStream):
    result = await llm.generate(intent.raw)
    level = await stream.report_signal(confidence=result.confidence)

    if level == "manual":
        decision = await stream.request_approval(
            prompt="Low confidence. Proceed with this result?",
            options=["yes", "no"],
        )
        if decision == "no":
            return {"status": "aborted"}

    return {"answer": result.text}
```

Each escalation emits an `AutonomyChangedEvent` on the wire so clients can show a "this request is now supervised" banner. Escalations are monotonic -- the level only gets stricter, never relaxes back.

Three levels are defined in `AutonomyLevel`:

| Level | Meaning |
|---|---|
| `auto` | Handler runs without intervention |
| `supervised` | Framework monitors but does not block |
| `manual` | Handler must request approval before proceeding |

## StreamStore and replay

When a `StreamStore` is configured, every emitted event is persisted so clients can reconnect and replay the event log. The default `InMemoryStreamStore` stores events in a dict keyed by `stream_id`.

After the stream completes, replay it with:

```bash
curl http://127.0.0.1:8000/agent/deploy/stream/<stream_id>
```

This returns the full event log as NDJSON, including the terminal `FinalEvent` or `ErrorEvent`.

The `StreamStore` protocol has five methods: `append`, `get_after`, `wait`, `mark_complete`, and `is_complete`. Implement it to back resumable streams with Redis or another external store for multi-host deployments.

## Audit integration

Every event emitted on a stream is automatically appended to the request's `ExecutionTrace.stream_events` list. This means streaming requests produce the same audit shape as non-streaming requests -- only with more detail. The audit recorder (whether in-memory or `SqliteAuditRecorder`) stores the complete event log.

## Runnable example

See [`examples/20_streaming_release_control/app.py`](https://github.com/shibuiwilliam/AgenticAPI/tree/main/examples/20_streaming_release_control) -- a release-control dashboard that demonstrates SSE and NDJSON transports, approval pause/resume, autonomy escalation, and stream replay.

```bash
uvicorn examples.20_streaming_release_control.app:app --reload
```

See also:

- [Approval Workflows](approval.md) -- the non-streaming approval mechanism
- [Observability](observability.md) -- OTEL span events from streaming requests
- [API Reference → Audit](../api/audit.md) -- `ExecutionTrace.stream_events` field
