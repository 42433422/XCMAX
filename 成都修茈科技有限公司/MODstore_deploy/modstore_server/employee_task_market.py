"""Employee task market for incident-driven autonomous claims.

Phase B moves incident handling from "human/rule assigns a brief" to a market:
incidents are the pool, employees are scored by capability, current load and
history, and the best candidate claims the task automatically.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from sqlalchemy import func

from modstore_server.employee_executor import execute_employee_task
from modstore_server.models import (
    CatalogItem,
    EmployeeExecutionMetric,
    EmployeeTriggerBinding,
    IncidentEvent,
    PendingBriefTask,
    User,
    get_session_factory,
)
from modstore_server.platform_llm_scope import platform_llm_scoped

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _admin_user_id(session) -> int:
    row = (
        session.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()
    )  # noqa: E712
    if row:
        return int(row.id)
    row = session.query(User).order_by(User.id.asc()).first()
    return int(row.id) if row else 0


def _payload(row: IncidentEvent) -> Dict[str, Any]:
    try:
        data = json.loads(row.payload_json or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _incident_priority(event_type: str, payload: Dict[str, Any]) -> int:
    explicit = payload.get("priority")
    try:
        if explicit is not None:
            return max(0, min(100, int(explicit)))
    except (TypeError, ValueError):
        pass
    event_type = str(event_type or "")
    if event_type == "security.alert":
        return 95
    if event_type in {"ci.failed", "on_quality_fail"}:
        return 85
    if event_type in {"on_error", "incident.unknown"}:
        return 75
    if event_type.startswith("employee."):
        return 55
    return 50


def _scope_from_incident(source: str, payload: Dict[str, Any]) -> str:
    explicit = str(payload.get("scope") or "").strip().lower()
    if explicit:
        return explicit
    text = " ".join(
        str(x or "")
        for x in (
            source,
            payload.get("path"),
            payload.get("summary"),
            payload.get("snippet"),
            payload.get("_unregistered_event_type"),
        )
    ).lower()
    if "xiu-ci.com" in text or "official" in text or "官网" in text:
        return "official_site"
    if "/fhd/" in text or "fhd" in text:
        return "fhd"
    if "modstore" in text or "modstore_deploy" in text:
        return "modstore"
    return "global"


def _catalog_employee_ids(session) -> set[str]:
    q = session.query(CatalogItem).filter(CatalogItem.artifact == "employee_pack")
    if hasattr(CatalogItem, "compliance_status"):
        q = q.filter(CatalogItem.compliance_status != "delisted")
    rows = q.all()
    return {str(row.pkg_id) for row in rows if str(row.pkg_id or "").strip()}


def _binding_candidates(session, event_type: str, source: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in (
        session.query(EmployeeTriggerBinding)
        .filter(EmployeeTriggerBinding.is_active.is_(True))
        .order_by(EmployeeTriggerBinding.priority.asc(), EmployeeTriggerBinding.id.asc())
        .all()
    ):
        stored = str(row.event_type or "").strip()
        if ":" in stored:
            base, filt = stored.split(":", 1)
            if base.strip() != event_type or filt.strip() != source:
                continue
        elif stored != event_type:
            continue
        eid = str(row.employee_id or "").strip()
        if eid:
            out[eid] = min(out.get(eid, 100), int(row.priority or 5))
    return out


def _recent_stats(session, employee_id: str, *, hours: int = 24) -> Dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours or 24)))
    rows = (
        session.query(EmployeeExecutionMetric.status, func.count(EmployeeExecutionMetric.id))
        .filter(
            EmployeeExecutionMetric.employee_id == employee_id,
            EmployeeExecutionMetric.created_at >= cutoff,
        )
        .group_by(EmployeeExecutionMetric.status)
        .all()
    )
    success = 0
    failure = 0
    for status, count in rows:
        if str(status or "") == "success":
            success += int(count or 0)
        else:
            failure += int(count or 0)
    running = (
        session.query(PendingBriefTask)
        .filter(
            PendingBriefTask.owner_employee_id == employee_id, PendingBriefTask.status == "running"
        )
        .count()
    )
    total = success + failure
    return {
        "failure": failure,
        "running": int(running or 0),
        "success": success,
        "success_rate": (success / total) if total else 0.72,
    }


def _score_candidate(
    *,
    employee_id: str,
    binding_priority: int,
    incident_priority: int,
    scope: str,
    stats: Dict[str, Any],
) -> Dict[str, Any]:
    eid = employee_id.lower()
    capability = max(0, 45 - int(binding_priority or 5) * 4)
    if scope != "global" and scope.replace("_", "-") in eid:
        capability += 8
    if "security" in eid or "guard" in eid:
        capability += 10 if incident_priority >= 90 else 0
    if "qa" in eid or "test" in eid:
        capability += 8 if incident_priority >= 80 else 0
    history = float(stats.get("success_rate") or 0.0) * 25
    load_penalty = int(stats.get("running") or 0) * 8
    failure_penalty = min(20, int(stats.get("failure") or 0) * 3)
    priority_bonus = incident_priority / 10.0
    score = round(
        max(0.0, capability + history + priority_bonus - load_penalty - failure_penalty), 3
    )
    return {
        "capability": round(capability, 3),
        "employee_id": employee_id,
        "history": round(history, 3),
        "incident_priority_bonus": round(priority_bonus, 3),
        "load_penalty": load_penalty,
        "recent_stats": stats,
        "score": score,
    }


def rank_market_candidates(event_id: int) -> Dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        ev = session.get(IncidentEvent, int(event_id))
        if ev is None:
            return {"ok": False, "reason": "incident_not_found"}
        payload = _payload(ev)
        scope = _scope_from_incident(str(ev.source or ""), payload)
        priority = _incident_priority(str(ev.event_type or ""), payload)
        catalog_ids = _catalog_employee_ids(session)
        bindings = _binding_candidates(session, str(ev.event_type or ""), str(ev.source or ""))
        candidates: List[Tuple[float, Dict[str, Any]]] = []
        for eid, bind_priority in bindings.items():
            if catalog_ids and eid not in catalog_ids:
                continue
            scored = _score_candidate(
                employee_id=eid,
                binding_priority=bind_priority,
                incident_priority=priority,
                scope=scope,
                stats=_recent_stats(session, eid),
            )
            candidates.append((float(scored["score"]), scored))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return {
            "candidates": [item[1] for item in candidates],
            "event_id": int(event_id),
            "incident_priority": priority,
            "ok": True,
            "scope": scope,
        }


@platform_llm_scoped
def dispatch_incident_via_market(event_id: int) -> Dict[str, Any]:
    if not _env_bool("MODSTORE_EMPLOYEE_TASK_MARKET_ENABLED", True):
        return {"ok": False, "claimed": False, "reason": "task_market_disabled"}
    ranked = rank_market_candidates(event_id)
    if not ranked.get("ok"):
        return {**ranked, "claimed": False}
    candidates = ranked.get("candidates") if isinstance(ranked.get("candidates"), list) else []
    if not candidates:
        return {**ranked, "claimed": False, "reason": "no_market_candidates"}
    chosen = candidates[0]
    employee_id = str(chosen.get("employee_id") or "").strip()
    if not employee_id:
        return {**ranked, "claimed": False, "reason": "empty_market_winner"}

    sf = get_session_factory()
    with sf() as session:
        ev = session.get(IncidentEvent, int(event_id))
        if ev is None:
            return {"ok": False, "claimed": False, "reason": "incident_not_found"}
        if int(ev.dispatched_count or 0) > 0 and not _env_bool(
            "MODSTORE_EMPLOYEE_TASK_MARKET_REDISPATCH", False
        ):
            return {"ok": True, "claimed": False, "reason": "incident_already_dispatched"}
        payload = _payload(ev)
        uid = _admin_user_id(session)
        summary = str(payload.get("summary") or ev.source or "incident")[:500]
        event_type = str(ev.event_type or "")
        source = str(ev.source or "")

    brief = f"[market-claim][{event_type}] {summary}"[:800]
    result = execute_employee_task(
        employee_id,
        brief,
        {
            "allow_high_risk_real_run": True,
            "incident": payload,
            "incident_market": {
                "all_candidates": candidates[:8],
                "claimed_by": employee_id,
                "event_id": int(event_id),
                "priority": ranked.get("incident_priority"),
                "scope": ranked.get("scope"),
                "selection_score": chosen.get("score"),
            },
            "source": source,
            "suppress_lifecycle_events": True,
            "unified_incident_bus": True,
        },
        user_id=uid,
    )
    with sf() as session:
        ev2 = session.get(IncidentEvent, int(event_id))
        if ev2 is not None:
            updated_payload = _payload(ev2)
            updated_payload["_market_claim"] = {
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "employee_id": employee_id,
                "score": chosen.get("score"),
                "scope": ranked.get("scope"),
            }
            ev2.payload_json = json.dumps(updated_payload, ensure_ascii=False)[:8000]
            ev2.dispatched_count = int(ev2.dispatched_count or 0) + 1
            session.commit()
    return {
        "claimed": True,
        "employee_id": employee_id,
        "event_id": int(event_id),
        "market": ranked,
        "ok": True,
        "result_ok": not bool(result.get("handler_failed")),
        "winner": chosen,
    }


def market_metrics(*, lookback_hours: int = 24) -> Dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours or 24)))
    sf = get_session_factory()
    with sf() as session:
        rows = (
            session.query(IncidentEvent)
            .filter(IncidentEvent.created_at >= cutoff)
            .order_by(IncidentEvent.id.desc())
            .all()
        )
    total = len(rows)
    claimed = 0
    by_employee: Dict[str, int] = {}
    for row in rows:
        payload = _payload(row)
        claim = payload.get("_market_claim") if isinstance(payload, dict) else None
        if isinstance(claim, dict) and claim.get("employee_id"):
            claimed += 1
            eid = str(claim.get("employee_id") or "")
            by_employee[eid] = by_employee.get(eid, 0) + 1
    return {
        "claimed": claimed,
        "claimed_ratio": (claimed / total) if total else 0.0,
        "lookback_hours": lookback_hours,
        "ok": True,
        "self_selected_task_ratio": (claimed / total) if total else 0.0,
        "total_incidents": total,
        "by_employee": by_employee,
    }


__all__ = ["dispatch_incident_via_market", "market_metrics", "rank_market_candidates"]
