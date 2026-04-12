"""Streaming release-control example: SSE, NDJSON, approval resume, and replay.

Demonstrates:
- ``AgentStream`` event emission from handlers
- ``streaming="sse"`` and ``streaming="ndjson"`` transports
- ``stream.request_approval()`` with ``POST /agent/{name}/resume/{stream_id}``
- ``GET /agent/{name}/stream/{stream_id}`` replay after completion
- ``AutonomyPolicy`` live escalation via ``stream.report_signal(...)``

Run with:
    uvicorn examples.20_streaming_release_control.app:app --reload

Or using the CLI:
    agenticapi dev --app examples.20_streaming_release_control.app:app

Try it with curl:
    # 1. Inspect the release catalogue
    curl -X POST http://127.0.0.1:8000/agent/releases.catalog \
        -H "Content-Type: application/json" \
        -d '{"intent": "List available release targets"}'

    # 2. Stream a rollout preview over SSE
    curl -N -X POST http://127.0.0.1:8000/agent/releases.preview \
        -H "Content-Type: application/json" \
        -d '{"intent": "Preview rollout for search-api v5.9.0 to production"}'

    # 3. Stream an execution request over NDJSON. The stream pauses at
    #    approval_requested and includes stream_id + approval_id.
    curl -N -X POST http://127.0.0.1:8000/agent/releases.execute \
        -H "Content-Type: application/json" \
        -d '{"intent": "Execute rollout for billing-api v2.4.0 to production"}'

    # 4. Resume the pending execution from a second terminal
    curl -X POST http://127.0.0.1:8000/agent/releases.execute/resume/<stream_id> \
        -H "Content-Type: application/json" \
        -d '{"approval_id": "<approval_id>", "decision": "approve"}'

    # 5. Replay the completed NDJSON event log later
    curl http://127.0.0.1:8000/agent/releases.execute/stream/<stream_id>
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from agenticapi import (
    AgentContext,
    AgenticApp,
    AgentRouter,
    AgentStream,
    AutonomyLevel,
    AutonomyPolicy,
    EscalateWhen,
    Intent,
)

STREAM_DELAY_SECONDS = 0.01
VERSION_RE = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")

SERVICES: dict[str, dict[str, Any]] = {
    "billing-api": {
        "owner": "revenue-platform",
        "current_version": "2.3.1",
        "error_budget_remaining_pct": 94,
        "recent_incidents_last_7d": 0,
        "canary_hosts": 4,
        "rollback_minutes": 6,
        "change_window_end_utc": "2026-04-12T18:00:00Z",
    },
    "search-api": {
        "owner": "discovery-platform",
        "current_version": "5.8.4",
        "error_budget_remaining_pct": 68,
        "recent_incidents_last_7d": 2,
        "canary_hosts": 2,
        "rollback_minutes": 12,
        "change_window_end_utc": "2026-04-12T17:30:00Z",
    },
    "identity-api": {
        "owner": "core-platform",
        "current_version": "1.12.0",
        "error_budget_remaining_pct": 89,
        "recent_incidents_last_7d": 1,
        "canary_hosts": 3,
        "rollback_minutes": 8,
        "change_window_end_utc": "2026-04-12T19:00:00Z",
    },
}

SERVICE_ALIASES = {
    "billing-api": "billing-api",
    "billing": "billing-api",
    "search-api": "search-api",
    "search": "search-api",
    "identity-api": "identity-api",
    "identity": "identity-api",
}

ROLLOUT_AUTONOMY = AutonomyPolicy(
    start=AutonomyLevel.AUTO,
    rules=[
        EscalateWhen(
            confidence_below=0.75,
            level=AutonomyLevel.SUPERVISED,
            reason="rollout confidence dropped below the operator-review threshold",
        ),
        EscalateWhen(
            policy_flagged=True,
            level=AutonomyLevel.MANUAL,
            reason="release policy flagged a high-risk production rollout",
        ),
    ],
)


def _detect_service(raw: str) -> str:
    raw_lower = raw.lower()
    for alias in sorted(SERVICE_ALIASES, key=len, reverse=True):
        if alias in raw_lower:
            return SERVICE_ALIASES[alias]
    return "billing-api"


def _detect_environment(raw: str) -> str:
    raw_lower = raw.lower()
    if "staging" in raw_lower:
        return "staging"
    if "prod" in raw_lower or "production" in raw_lower:
        return "production"
    return "production"


def _next_version(current_version: str) -> str:
    major, minor, patch = (int(part) for part in current_version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def _parse_release_request(raw: str) -> dict[str, str]:
    service = _detect_service(raw)
    profile = SERVICES[service]
    match = VERSION_RE.search(raw)
    version = match.group(1) if match else _next_version(profile["current_version"])
    environment = _detect_environment(raw)
    return {
        "service": service,
        "target_version": version,
        "environment": environment,
    }


def _assess_risk(profile: dict[str, Any], environment: str) -> dict[str, Any]:
    score = 25
    factors: list[str] = []

    if environment == "production":
        score += 15
        factors.append("production change window")

    if profile["error_budget_remaining_pct"] < 80:
        score += 20
        factors.append(f"error budget at {profile['error_budget_remaining_pct']}%")

    if profile["recent_incidents_last_7d"] > 0:
        incident_score = min(20, profile["recent_incidents_last_7d"] * 8)
        score += incident_score
        factors.append(f"{profile['recent_incidents_last_7d']} recent incidents")

    if profile["canary_hosts"] < 3:
        score += 10
        factors.append(f"only {profile['canary_hosts']} canary hosts")

    score = min(score, 100)

    if score >= 85:
        return {
            "risk_score": score,
            "risk_level": "high",
            "confidence": 0.58,
            "policy_flagged": True,
            "factors": factors or ["manual operator review required"],
        }
    if score >= 60:
        return {
            "risk_score": score,
            "risk_level": "medium",
            "confidence": 0.72,
            "policy_flagged": False,
            "factors": factors or ["extra review recommended"],
        }
    return {
        "risk_score": score,
        "risk_level": "low",
        "confidence": 0.93,
        "policy_flagged": False,
        "factors": factors or ["standard rollout posture"],
    }


def _build_checklist(
    *,
    service: str,
    profile: dict[str, Any],
    target_version: str,
    environment: str,
) -> list[dict[str, Any]]:
    return [
        {
            "step": "catalog_lookup",
            "status": "ready",
            "details": f"{service} moves from {profile['current_version']} to {target_version}",
        },
        {
            "step": "canary_plan",
            "status": "watch" if profile["canary_hosts"] < 3 else "ready",
            "details": f"Canary rollout starts on {profile['canary_hosts']} hosts in {environment}",
        },
        {
            "step": "rollback_window",
            "status": "ready",
            "details": f"Rollback completes in about {profile['rollback_minutes']} minutes",
        },
        {
            "step": "change_window",
            "status": "ready",
            "details": f"Approved deployment window closes at {profile['change_window_end_utc']}",
        },
    ]


async def _pause() -> None:
    await asyncio.sleep(STREAM_DELAY_SECONDS)


async def _emit_tool_exchange(
    stream: AgentStream,
    *,
    call_id: str,
    name: str,
    arguments: dict[str, Any],
    result_summary: str,
) -> None:
    await stream.emit_tool_call_started(call_id=call_id, name=name, arguments=arguments)
    await _pause()
    await stream.emit_tool_call_completed(
        call_id=call_id,
        result_summary=result_summary,
        duration_ms=STREAM_DELAY_SECONDS * 1000,
    )


async def _emit_checklist(stream: AgentStream, checklist: list[dict[str, Any]]) -> None:
    total = len(checklist)
    for index, item in enumerate(checklist, start=1):
        await _pause()
        await stream.emit_partial(
            {
                "index": index,
                "total": total,
                **item,
            },
            is_last=index == total,
        )


def _release_id(service: str, version: str) -> str:
    compact_service = service.replace("-", "")[:8]
    compact_version = version.replace(".", "")
    return f"rel-{compact_service}-{compact_version}"


router = AgentRouter(prefix="releases", tags=["streaming", "release-control"])


@router.agent_endpoint(
    name="catalog",
    description="List release targets and the guardrails used by the streaming demo",
    autonomy_level="auto",
)
async def releases_catalog(intent: Intent, context: AgentContext) -> dict[str, Any]:
    targets = [
        {
            "service": service,
            "current_version": profile["current_version"],
            "owner": profile["owner"],
            "error_budget_remaining_pct": profile["error_budget_remaining_pct"],
            "recent_incidents_last_7d": profile["recent_incidents_last_7d"],
            "canary_hosts": profile["canary_hosts"],
        }
        for service, profile in SERVICES.items()
    ]
    return {
        "targets": targets,
        "default_environment": "production",
        "example_preview_intent": "Preview rollout for search-api v5.9.0 to production",
        "example_execute_intent": "Execute rollout for billing-api v2.4.0 to production",
    }


@router.agent_endpoint(
    name="preview",
    description="Stream a rollout preview over SSE with live risk and autonomy events",
    autonomy=ROLLOUT_AUTONOMY,
    streaming="sse",
)
async def releases_preview(intent: Intent, context: AgentContext, stream: AgentStream) -> dict[str, Any]:
    request = _parse_release_request(intent.raw)
    profile = SERVICES[request["service"]]
    risk = _assess_risk(profile, request["environment"])
    checklist = _build_checklist(
        service=request["service"],
        profile=profile,
        target_version=request["target_version"],
        environment=request["environment"],
    )

    await stream.emit_thought(
        f"Reviewing {request['service']} {profile['current_version']} -> {request['target_version']} "
        f"for {request['environment']}."
    )
    await _emit_tool_exchange(
        stream,
        call_id="catalog_lookup",
        name="release_catalog.lookup",
        arguments={"service": request["service"]},
        result_summary=f"owner={profile['owner']}, current_version={profile['current_version']}",
    )
    await stream.emit_thought("Scoring rollout risk from incidents, error budget, and canary capacity.")
    await stream.report_signal(
        confidence=risk["confidence"],
        policy_flagged=risk["policy_flagged"],
        note="preview risk assessment",
    )
    await _emit_tool_exchange(
        stream,
        call_id="window_validate",
        name="change_window.validate",
        arguments={"environment": request["environment"], "service": request["service"]},
        result_summary=f"window open until {profile['change_window_end_utc']}",
    )
    await stream.emit_partial(
        {
            "summary": "risk assessed",
            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "current_autonomy_level": stream.current_autonomy_level,
            "factors": risk["factors"],
        }
    )
    await _emit_checklist(stream, checklist)

    return {
        "stream_id": stream.stream_id,
        "service": request["service"],
        "target_version": request["target_version"],
        "environment": request["environment"],
        "owner": profile["owner"],
        "risk_level": risk["risk_level"],
        "risk_score": risk["risk_score"],
        "current_autonomy_level": stream.current_autonomy_level,
        "risk_factors": risk["factors"],
        "checklist": checklist,
        "replay_path": f"/agent/releases.preview/stream/{stream.stream_id}",
    }


@router.agent_endpoint(
    name="execute",
    description="Stream an execution request over NDJSON, pause for approval, then queue the rollout",
    autonomy=ROLLOUT_AUTONOMY,
    streaming="ndjson",
)
async def releases_execute(intent: Intent, context: AgentContext, stream: AgentStream) -> dict[str, Any]:
    request = _parse_release_request(intent.raw)
    profile = SERVICES[request["service"]]
    risk = _assess_risk(profile, request["environment"])
    release_id = _release_id(request["service"], request["target_version"])

    await stream.emit_thought("Building the execution plan and validating the change window.")
    await _emit_tool_exchange(
        stream,
        call_id="window_validate",
        name="change_window.validate",
        arguments={"service": request["service"], "environment": request["environment"]},
        result_summary=f"window open until {profile['change_window_end_utc']}",
    )
    await stream.report_signal(
        confidence=risk["confidence"],
        policy_flagged=risk["policy_flagged"],
        note="execution preflight",
    )
    await stream.emit_partial(
        {
            "status": "preflight_complete",
            "service": request["service"],
            "target_version": request["target_version"],
            "risk_level": risk["risk_level"],
            "risk_score": risk["risk_score"],
            "current_autonomy_level": stream.current_autonomy_level,
        }
    )

    decision = await stream.request_approval(
        prompt=(
            f"Approve rollout {release_id} for {request['service']} {request['target_version']} "
            f"to {request['environment']}? Risk={risk['risk_level']} ({risk['risk_score']}/100)."
        ),
        options=["approve", "reject"],
        timeout_seconds=30.0,
    )

    if decision != "approve":
        await stream.emit_partial(
            {
                "status": "aborted",
                "approval_decision": decision,
                "reason": "operator rejected the rollout",
            },
            is_last=True,
        )
        return {
            "stream_id": stream.stream_id,
            "release_id": release_id,
            "service": request["service"],
            "target_version": request["target_version"],
            "environment": request["environment"],
            "status": "aborted",
            "approval_decision": decision,
            "current_autonomy_level": stream.current_autonomy_level,
            "replay_path": f"/agent/releases.execute/stream/{stream.stream_id}",
        }

    await _emit_tool_exchange(
        stream,
        call_id="queue_enqueue",
        name="deployment_queue.enqueue",
        arguments={
            "release_id": release_id,
            "service": request["service"],
            "target_version": request["target_version"],
        },
        result_summary=f"queued rollout job {release_id}",
    )
    await stream.emit_partial(
        {
            "status": "queued",
            "release_id": release_id,
            "owner": profile["owner"],
            "next_step": "Observe the canary for 15 minutes before widening traffic.",
        },
        is_last=True,
    )
    return {
        "stream_id": stream.stream_id,
        "release_id": release_id,
        "service": request["service"],
        "target_version": request["target_version"],
        "environment": request["environment"],
        "status": "queued",
        "approval_decision": decision,
        "owner": profile["owner"],
        "current_autonomy_level": stream.current_autonomy_level,
        "replay_path": f"/agent/releases.execute/stream/{stream.stream_id}",
    }


app = AgenticApp(
    title="Streaming Release Control",
    version="0.1.0",
    description=(
        "Focused streaming example covering SSE, NDJSON, in-request approval resume, "
        "replay, and live autonomy escalation."
    ),
)
app.include_router(router)
