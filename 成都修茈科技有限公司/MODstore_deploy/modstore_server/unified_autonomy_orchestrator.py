"""Phase-D cross-repository incident orchestrator."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

from modstore_server.models import IncidentEvent, get_session_factory

KNOWN_SCOPES = ("fhd", "modstore", "website", "desktop", "android")


def _scope(payload: Dict[str, Any], source: str) -> str:
    raw = str(payload.get("scope") or source or "global").strip().lower()
    aliases = {
        "官网": "website",
        "安卓": "android",
        "桌面": "desktop",
        "管理端": "fhd",
    }
    raw = aliases.get(raw, raw)
    for scope in KNOWN_SCOPES:
        if scope in raw:
            return scope
    return "global"


def _priority(event_type: str, payload: Dict[str, Any], scope: str) -> int:
    try:
        base = int(payload.get("priority")) if payload.get("priority") is not None else 60
    except (TypeError, ValueError):
        base = 60
    text = json.dumps({"event_type": event_type, "payload": payload}, ensure_ascii=False).lower()
    if any(
        token in text
        for token in ("security", "secret", "credential", "payment", "auth", "安全", "支付")
    ):
        base += 25
    if any(token in text for token in ("down", "outage", "500", "crash", "slo", "不可用", "宕机")):
        base += 18
    if event_type in {"on_error", "incident.unknown"}:
        base += 8
    scope_weight = {
        "android": 8,
        "desktop": 8,
        "website": 7,
        "fhd": 6,
        "modstore": 6,
        "global": 5,
    }.get(scope, 5)
    return max(0, min(base + scope_weight, 100))


def _resource_plan(scope: str, priority: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from modstore_server.node_coordinator import cluster_status

        cluster = cluster_status()
        leader = cluster.get("leader") if isinstance(cluster.get("leader"), dict) else None
    except Exception as exc:
        cluster = {"ok": False, "error": str(exc)[:300]}
        leader = None
    worker_pool = {
        "android": "device_pool",
        "desktop": "desktop_pool",
        "fhd": "backend_pool",
        "modstore": "backend_pool",
        "website": "web_pool",
    }.get(scope, "general_pool")
    resource_class = "exclusive" if priority >= 90 else "normal"
    if bool(payload.get("requires_device")) or scope in {"android", "desktop"}:
        resource_class = "device_exclusive"
    return {
        "cluster": cluster,
        "leader": leader,
        "resource_class": resource_class,
        "worker_pool": worker_pool,
    }


def orchestrate_incident(event_id: int) -> Dict[str, Any]:
    """Normalize incident priority and resource routing across all repos."""

    sf = get_session_factory()
    with sf() as session:
        ev = session.query(IncidentEvent).filter(IncidentEvent.id == int(event_id)).first()
        if not ev:
            return {"ok": False, "reason": "incident_not_found"}
        try:
            payload = json.loads(ev.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        scope = _scope(payload, str(ev.source or ""))
        priority = _priority(str(ev.event_type or ""), payload, scope)
        try:
            from modstore_server.incident_model_router import route_for_incident

            model_route = route_for_incident(
                event_type=str(ev.event_type or ""),
                payload={**payload, "priority": priority, "scope": scope},
            )
        except Exception as exc:
            model_route = {"error": str(exc)[:300], "route": "auto"}
        plan = {
            "coverage_scopes": list(KNOWN_SCOPES),
            "event_id": int(event_id),
            "model_route": model_route,
            "priority": priority,
            "resource_plan": _resource_plan(scope, priority, payload),
            "schema_version": 1,
            "scope": scope,
            "should_dispatch": True,
            "source": "phase_d_unified_orchestrator",
            "ts": time.time(),
        }
        payload["_unified_orchestration"] = plan
        payload["priority"] = priority
        payload["scope"] = scope
        ev.payload_json = json.dumps(payload, ensure_ascii=False)[:8000]
        session.commit()
        return {"ok": True, **plan}


__all__ = ["orchestrate_incident", "KNOWN_SCOPES"]
