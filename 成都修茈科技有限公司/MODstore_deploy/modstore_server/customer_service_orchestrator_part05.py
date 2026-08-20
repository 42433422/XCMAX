# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def ticket_lifecycle_stage(status: str | None = None, decision_status: str | None = None) -> int:
    """用户侧五阶段：1已收到 → 2处理中 → 3有结果 → 4待补充 → 5已完成。"""
    s = str(status or "").strip().lower()
    d = str(decision_status or "").strip().lower()
    if s in {"resolved", "closed", "done", "rejected"}:
        return 5
    if s == "waiting_user" or d == "needs_more_info":
        return 4
    if s in {"open", "pending", "queued"}:
        return 1
    if s == "processing":
        if d in {"approved", "rejected"}:
            return 3
        return 2
    if d in {"approved", "rejected"}:
        return 3
    return 1


def _summarize_incident_team_rows(
    team_rows: list[_facade().Dict[str, _facade().Any]],
) -> str:
    """把 incident team / 员工执行行压缩成用户可读的一句进度。"""
    bits: list[str] = []
    role_cn = {"scout": "排查", "fix": "修复", "verify": "验证"}
    for row in team_rows or []:
        if not isinstance(row, dict):
            continue
        role = role_cn.get(str(row.get("role") or "").strip(), str(row.get("role") or "执行"))
        emp = str(row.get("employee_id") or "").strip() or "值班员工"
        ok = bool(row.get("ok"))
        status = str(row.get("status") or "").strip()
        if ok:
            bits.append(f"{role}（{emp}）已完成")
        elif status:
            bits.append(f"{role}（{emp}）未完成（{status}）")
        else:
            bits.append(f"{role}（{emp}）未完成")
    return "；".join(bits[:6]) if bits else "值班员工已接手"


def apply_customer_ticket_incident_progress(
    db: _facade().Session,
    *,
    ticket_id: int,
    event_id: int = 0,
    team_ok: bool = False,
    team_rows: _facade().Optional[list[_facade().Dict[str, _facade().Any]]] = None,
    summary_hint: str = "",
) -> _facade().Dict[str, _facade().Any]:
    """把 AI 员工 / incident team 执行结果回写到已有客服工单。

    复用现有 ``CustomerServiceMessage`` / ``CustomerServiceAction`` / ``audit``，
    不新建旁路表：推进到「有结果」（processing+approved），全员成功时可结案。
    """
    ticket = (
        db.query(_facade().CustomerServiceTicket)
        .filter(_facade().CustomerServiceTicket.id == int(ticket_id))
        .first()
    )
    if not ticket:
        return {"ok": False, "reason": "ticket_not_found"}
    ev = _facade().json_loads(ticket.evidence_json, {})
    if not isinstance(ev, dict):
        ev = {}
    delivery_managed = _facade().delivery_policy.is_delivery_managed(ticket.intent, ev)
    rows = [r for r in team_rows or [] if isinstance(r, dict)]
    progress = _facade()._summarize_incident_team_rows(rows)
    hint = str(summary_hint or ticket.summary or ticket.title or "").strip()[:120]
    if team_ok:
        reply = _facade().delivery_policy.success_reply(
            hint or ticket.ticket_no, progress, delivery_managed
        )
    else:
        reply = f"我是小C。工单「{hint or ticket.ticket_no}」已有员工处理进展：{progress}。我们会继续跟进，也可继续补充截图或具体页面。"
    action = _facade().build_action(
        db,
        ticket_id=int(ticket.id),
        user_id=int(ticket.user_id or 0),
        action_type="employee.dispatch",
        target_type="incident_team",
        target_id=str(event_id or "")[:240],
        request={
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "roles": [
                {
                    "role": r.get("role"),
                    "employee_id": r.get("employee_id"),
                    "ok": bool(r.get("ok")),
                    "status": r.get("status"),
                }
                for r in rows[:8]
            ],
        },
    )
    action.status = "completed"
    action.result_json = _facade().json_dumps(
        {
            "ok": bool(team_ok),
            "progress": progress,
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
        }
    )
    action.error = ""
    db.flush()
    _facade().delivery_policy.apply_ticket_outcome(ticket, team_ok, delivery_managed)
    reports = list(ev.get("employee_reports") or [])
    reports.append(
        {
            "type": "incident_team",
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "progress": progress[:500],
            "at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
    )
    ev["employee_reports"] = reports[-20:]
    ticket.evidence_json = _facade().json_dumps(ev)
    assistant_msg = _facade().CustomerServiceMessage(
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        user_id=int(ticket.user_id or 0),
        role="assistant",
        content=reply,
        payload_json=_facade().json_dumps(
            {
                "ticket": _facade().ticket_payload(ticket),
                "cards": [
                    {
                        "type": "ticket",
                        "title": ticket.title,
                        "ticket_no": ticket.ticket_no,
                        "status": ticket.status,
                        "intent": ticket.intent,
                        **_facade().ticket_lifecycle_payload(ticket.status, ticket.decision_status),
                    }
                ],
                "employee_progress": {
                    "event_id": int(event_id or 0),
                    "team_ok": bool(team_ok),
                    "progress": progress,
                },
            }
        ),
    )
    db.add(assistant_msg)
    _facade().audit(
        db,
        event_type="employee_progress",
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        actor_type="system",
        detail={
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "progress": progress[:500],
            "action_id": int(action.id or 0),
        },
    )
    _facade().enqueue_customer_service_event(
        db,
        "customer_service.employee_progress",
        f"{ticket.ticket_no}:progress:{event_id or action.id}",
        {
            "ticket_id": int(ticket.id),
            "ticket_no": ticket.ticket_no,
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "lifecycle_stage": _facade().ticket_lifecycle_stage(
                ticket.status, ticket.decision_status
            ),
        },
    )
    db.flush()
    return {
        "ok": True,
        "ticket_id": int(ticket.id),
        "lifecycle_stage": _facade().ticket_lifecycle_stage(ticket.status, ticket.decision_status),
        "lifecycle_label": _facade()
        .ticket_lifecycle_payload(ticket.status, ticket.decision_status)
        .get("lifecycle_label"),
        "message_id": int(assistant_msg.id or 0),
        "action_id": int(action.id or 0),
        "team_ok": bool(team_ok),
    }


def ticket_lifecycle_payload(
    status: str | None = None, decision_status: str | None = None
) -> _facade().Dict[str, _facade().Any]:
    stage = _facade().ticket_lifecycle_stage(status, decision_status)
    label = next(
        (name for (num, name) in _facade().TICKET_LIFECYCLE_STEPS if num == stage),
        "已收到",
    )
    return {
        "lifecycle_stage": stage,
        "lifecycle_label": label,
        "lifecycle_steps": [
            {
                "stage": num,
                "label": name,
                "state": "done" if num < stage else "current" if num == stage else "todo",
            }
            for (num, name) in _facade().TICKET_LIFECYCLE_STEPS
        ],
    }


def ticket_payload(
    row: _facade().CustomerServiceTicket,
) -> _facade().Dict[str, _facade().Any]:
    life = _facade().ticket_lifecycle_payload(row.status, row.decision_status)
    evidence = _facade().json_loads(row.evidence_json, {})
    if not isinstance(evidence, dict):
        evidence = {}
    domain = str(evidence.get("issue_domain") or "").strip().lower()
    if domain not in _facade().ISSUE_DOMAINS:
        domain = ""
    return {
        "id": row.id,
        "session_id": row.session_id,
        "ticket_no": row.ticket_no,
        "title": row.title,
        "intent": row.intent,
        "issue_domain": domain or None,
        "issue_domain_label": evidence.get("issue_domain_label")
        or _facade().ISSUE_DOMAIN_LABELS.get(domain)
        or None,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "status": row.status,
        "priority": row.priority,
        "evidence": evidence,
        "summary": row.summary,
        "decision_status": row.decision_status,
        "automation_level": row.automation_level,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "closed_at": row.closed_at.isoformat() if row.closed_at else "",
        **life,
    }


def decision_payload(
    row: _facade().CustomerServiceDecision,
) -> _facade().Dict[str, _facade().Any]:
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "standard_id": row.standard_id,
        "intent": row.intent,
        "decision": row.decision,
        "risk_level": row.risk_level,
        "confidence": row.confidence,
        "rationale": row.rationale,
        "extracted": _facade().json_loads(row.extracted_json, {}),
        "criteria": _facade().json_loads(row.criteria_json, []),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def action_payload(row: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "decision_id": row.decision_id,
        "action_type": row.action_type,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "status": row.status,
        "request": _facade().json_loads(row.request_json, {}),
        "result": _facade().json_loads(row.result_json, {}),
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }
