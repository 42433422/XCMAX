"""Dynamic multi-agent incident team orchestration."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from modstore_server.employee_executor import execute_employee_task
from modstore_server.models import IncidentEvent, User, get_session_factory

ROLE_FALLBACKS = {
    "scout": ["change-request-auditor", "daily-orchestrator"],
    "fix": ["vibe-coding-maintainer", "daily-orchestrator"],
    "verify": ["test-qa-runner", "change-request-auditor"],
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _payload(row: IncidentEvent) -> Dict[str, Any]:
    try:
        data = json.loads(row.payload_json or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _admin_user_id(session) -> int:
    row = (
        session.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()
    )  # noqa: E712
    if row:
        return int(row.id)
    row = session.query(User).order_by(User.id.asc()).first()
    return int(row.id) if row else 0


def _role_override(role: str) -> str:
    key = f"MODSTORE_INCIDENT_TEAM_{role.upper()}_EMPLOYEE"
    return (os.environ.get(key) or "").strip()


def _candidate_ids(event_id: int) -> List[str]:
    return [
        str(row.get("employee_id") or "")
        for row in _candidate_rows(event_id)
        if isinstance(row, dict) and str(row.get("employee_id") or "").strip()
    ]


def _candidate_rows(event_id: int) -> List[Dict[str, Any]]:
    try:
        from modstore_server.employee_task_market import rank_market_candidates

        ranked = rank_market_candidates(event_id)
        rows = ranked.get("candidates") if isinstance(ranked.get("candidates"), list) else []
        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []


def _pick_role(role: str, candidates: List[str], used: set[str]) -> str:
    override = _role_override(role)
    if override and override not in used:
        return override
    preferred_exact = {
        "fix": (
            "code-validator",
            "vibe-coding-maintainer",
            "workflow-automator",
            "daily-orchestrator",
        ),
        "scout": (
            "workflow-automator",
            "self-checker",
            "host-checker",
            "intent-analyst",
            "quality-validator",
        ),
        "verify": (
            "sandbox-tester",
            "test-qa-runner",
            "quality-validator",
            "change-request-auditor",
        ),
    }.get(role, ())
    for eid in preferred_exact:
        if eid in candidates and eid not in used:
            return eid
    role_terms = {
        "fix": ("fix", "maintainer", "vibe", "code", "orchestrator"),
        "scout": (
            "workflow",
            "self",
            "host",
            "intent",
            "quality",
            "triage",
            "audit",
            "review",
            "security",
            "guard",
        ),
        "verify": ("qa", "test", "verify", "auditor"),
    }.get(role, ())
    for eid in candidates:
        low = eid.lower()
        if eid not in used and any(term in low for term in role_terms):
            return eid
    for eid in candidates:
        if eid and eid not in used:
            return eid
    for eid in ROLE_FALLBACKS.get(role, []):
        if eid not in used:
            return eid
    return ""


def build_incident_team(event_id: int) -> Dict[str, Any]:
    candidate_rows = _candidate_rows(event_id)
    candidates = [
        str(row.get("employee_id") or "")
        for row in candidate_rows
        if str(row.get("employee_id") or "").strip()
    ]
    code_owner = ""
    code_owner_match: Dict[str, Any] = {}
    for row in candidate_rows:
        ownership = row.get("code_ownership") if isinstance(row.get("code_ownership"), dict) else {}
        if ownership.get("match_count"):
            code_owner = str(row.get("employee_id") or "").strip()
            code_owner_match = ownership
            break
    used: set[str] = set()
    team: List[Dict[str, str]] = []
    for role in ("scout", "fix", "verify"):
        if role == "fix" and code_owner and code_owner not in used:
            eid = code_owner
        else:
            reserved = {code_owner} if code_owner and role == "scout" else set()
            eid = _pick_role(role, candidates, used | reserved)
        if eid:
            used.add(eid)
            team.append({"employee_id": eid, "role": role})
    return {
        "candidates": candidates,
        "code_owner": code_owner,
        "code_owner_match": code_owner_match,
        "event_id": int(event_id),
        "team": team,
    }


def _task_for_role(
    *,
    code_ownership: Optional[Dict[str, Any]] = None,
    event_type: str,
    payload: Dict[str, Any],
    role: str,
    scout_result: Optional[Dict[str, Any]] = None,
    fix_result: Optional[Dict[str, Any]] = None,
) -> str:
    summary = str(payload.get("summary") or event_type or "incident")
    base = (
        f"你是事故处理小组的 {role}。事件类型：{event_type}。问题摘要：{summary}。\n"
        "回复必须说人话：先给结论/状态，再说原因，再说下一步；不要直接倾倒 JSON、内部字段或英文模板。"
    )
    ownership_text = ""
    if isinstance(code_ownership, dict) and code_ownership:
        files = [
            str(item).strip()
            for item in (code_ownership.get("matched_files") or [])
            if str(item or "").strip()
        ][:8]
        globs = [
            str(item).strip()
            for item in (code_ownership.get("matched_globs") or [])
            if str(item or "").strip()
        ][:6]
        bits = ["\n你是本事故命中的代码负责人，必须围绕归属代码给可执行处理。"]
        if files:
            bits.append("命中文件：" + "、".join(files))
        if globs:
            bits.append("归属规则：" + "、".join(globs))
        ownership_text = "\n".join(bits)
    if role == "scout":
        return base + "你的任务是判断最可能的原因、影响范围、严重程度和安全的下一步。"
    if role == "fix":
        return base + (
            "你的任务是执行或委派最小安全修复。可参考前面排查结果，但输出时要翻译成人话。"
            f"{ownership_text}"
            f"\n排查结果：{json.dumps(scout_result or {}, ensure_ascii=False)[:4000]}"
        )
    return base + (
        "你的任务是验证修复或恢复路径。用 PASS/FAIL 开头，并给出证据和剩余风险。"
        f"\n排查结果：{json.dumps(scout_result or {}, ensure_ascii=False)[:3000]}"
        f"\n修复结果：{json.dumps(fix_result or {}, ensure_ascii=False)[:3000]}"
    )


def dispatch_incident_team(event_id: int) -> Dict[str, Any]:
    if not _env_bool("MODSTORE_INCIDENT_TEAM_ENABLED", True):
        return {"claimed": False, "ok": False, "reason": "incident_team_disabled"}
    team_plan = build_incident_team(event_id)
    team = team_plan.get("team") if isinstance(team_plan.get("team"), list) else []
    if len(team) < 2:
        return {**team_plan, "claimed": False, "ok": False, "reason": "insufficient_team"}

    sf = get_session_factory()
    with sf() as session:
        ev = session.get(IncidentEvent, int(event_id))
        if ev is None:
            return {"claimed": False, "ok": False, "reason": "incident_not_found"}
        if int(ev.dispatched_count or 0) > 0 and not _env_bool(
            "MODSTORE_INCIDENT_TEAM_REDISPATCH", False
        ):
            return {"claimed": False, "ok": True, "reason": "incident_already_dispatched"}
        payload = _payload(ev)
        event_type = str(ev.event_type or "")
        source = str(ev.source or "")
        uid = _admin_user_id(session)

    recovery: Dict[str, Any] = {}
    try:
        from modstore_server.release_recovery_orchestrator import maybe_execute_recovery

        recovery = maybe_execute_recovery(event_id=event_id, event_type=event_type, payload=payload)
    except Exception as exc:
        recovery = {"ok": False, "error": str(exc)[:500]}

    results: List[Dict[str, Any]] = []
    scout_result: Optional[Dict[str, Any]] = None
    fix_result: Optional[Dict[str, Any]] = None
    for member in team:
        role = str(member.get("role") or "")
        employee_id = str(member.get("employee_id") or "")
        if not role or not employee_id:
            continue
        route: Dict[str, Any] = {}
        bench_override = None
        try:
            from modstore_server.incident_model_router import (
                bench_override_for_route,
                route_for_incident,
            )

            route = route_for_incident(event_type=event_type, payload=payload, role=role)
            bench_override = bench_override_for_route(route)
        except Exception:
            route = {"provider": "auto", "model": "auto", "reason": "router_error"}
        task = _task_for_role(
            code_ownership=(
                team_plan.get("code_owner_match")
                if role == "fix" and isinstance(team_plan.get("code_owner_match"), dict)
                else None
            ),
            event_type=event_type,
            fix_result=fix_result,
            payload=payload,
            role=role,
            scout_result=scout_result,
        )
        result = execute_employee_task(
            employee_id,
            task,
            {
                "allow_high_risk_real_run": role in {"fix", "verify"},
                "allow_medium_risk": True,
                "incident": payload,
                "incident_team": team_plan,
                "model_route": route,
                "release_recovery": recovery,
                "role": role,
                "source": source,
                "suppress_lifecycle_events": True,
                "unified_incident_bus": True,
            },
            user_id=uid,
            bench_llm_override=bench_override,
        )
        status = str(result.get("status") or result.get("execution_status") or "").strip().lower()
        risk_blocked = (
            status == "blocked_by_risk_gate"
            or bool(result.get("blocked_by_risk_gate"))
            or str(result.get("reason") or "").strip().lower() == "blocked_by_risk_gate"
        )
        row = {
            "employee_id": employee_id,
            "ok": (
                not risk_blocked
                and not bool(result.get("handler_failed"))
                and not bool(result.get("error"))
                and status not in {"handler_failed", "orchestrator_failed", "failed"}
            ),
            "role": role,
            "route": route,
            "result": result,
            "status": status or ("blocked_by_risk_gate" if risk_blocked else "unknown"),
        }
        results.append(row)
        if role == "scout":
            scout_result = row
        elif role == "fix":
            fix_result = row

    ok = bool(results) and all(bool(row.get("ok")) for row in results if row.get("role") != "fix")
    with sf() as session:
        ev2 = session.get(IncidentEvent, int(event_id))
        if ev2 is not None:
            updated = _payload(ev2)
            updated["_team_claim"] = {
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "ok": ok,
                "recovery": recovery,
                "team": [{k: v for k, v in row.items() if k != "result"} for row in results],
            }
            ev2.payload_json = json.dumps(updated, ensure_ascii=False)[:8000]
            ev2.dispatched_count = int(ev2.dispatched_count or 0) + 1
            session.commit()
    return {
        "claimed": True,
        "event_id": int(event_id),
        "ok": ok,
        "recovery": recovery,
        "results": results,
        "team": team_plan,
    }


__all__ = ["build_incident_team", "dispatch_incident_team"]
