"""Customer-service incident progress application (extracted for source-governance)."""
from __future__ import annotations

from typing import Any

def apply_customer_ticket_incident_progress(
    db: Session,
    *,
    ticket_id: int,
    event_id: int = 0,
    team_ok: bool = False,
    team_rows: Optional[list[Dict[str, Any]]] = None,
    summary_hint: str = "",
) -> Dict[str, Any]:
    """把 AI 员工 / incident team 执行结果回写到已有客服工单。

    复用现有 ``CustomerServiceMessage`` / ``CustomerServiceAction`` / ``audit``，
    不新建旁路表：推进到「有结果」（processing+approved），全员成功时可结案。
    """
    ticket = (
        db.query(CustomerServiceTicket).filter(CustomerServiceTicket.id == int(ticket_id)).first()
    )
    if not ticket:
        return {"ok": False, "reason": "ticket_not_found"}

    rows = [r for r in (team_rows or []) if isinstance(r, dict)]
    progress = _summarize_incident_team_rows(rows)
    hint = str(summary_hint or ticket.summary or ticket.title or "").strip()[:120]
    if team_ok:
        reply = (
            f"我是小C。工单「{hint or ticket.ticket_no}」值班员工已完成排查修复并验证通过。"
            f"进展：{progress}。如仍复现请再补充截图。"
        )
    else:
        reply = (
            f"我是小C。工单「{hint or ticket.ticket_no}」已有员工处理进展："
            f"{progress}。我们会继续跟进，也可继续补充截图或具体页面。"
        )

    action = build_action(
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
    # 回写本身成功即 completed；员工修复是否通过放 result，避免用户侧「转交失败」红字
    action.status = "completed"
    action.result_json = json_dumps(
        {
            "ok": bool(team_ok),
            "progress": progress,
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
        }
    )
    action.error = ""
    db.flush()

    # 有员工结论 → decision_status=approved 进入「有结果」；仅全员成功才结案
    ticket.decision_status = "approved"
    if team_ok:
        ticket.status = "resolved"
        ticket.closed_at = datetime.now(timezone.utc)
    else:
        ticket.status = "processing"
        ticket.closed_at = None
    ticket.updated_at = datetime.now(timezone.utc)

    ev = json_loads(ticket.evidence_json, {})
    if not isinstance(ev, dict):
        ev = {}
    reports = list(ev.get("employee_reports") or [])
    reports.append(
        {
            "type": "incident_team",
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "progress": progress[:500],
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    ev["employee_reports"] = reports[-20:]
    ticket.evidence_json = json_dumps(ev)

    assistant_msg = CustomerServiceMessage(
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        user_id=int(ticket.user_id or 0),
        role="assistant",
        content=reply,
        payload_json=json_dumps(
            {
                "ticket": ticket_payload(ticket),
                "cards": [
                    {
                        "type": "ticket",
                        "title": ticket.title,
                        "ticket_no": ticket.ticket_no,
                        "status": ticket.status,
                        "intent": ticket.intent,
                        **ticket_lifecycle_payload(ticket.status, ticket.decision_status),
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
    audit(
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
    enqueue_customer_service_event(
        db,
        "customer_service.employee_progress",
        f"{ticket.ticket_no}:progress:{event_id or action.id}",
        {
            "ticket_id": int(ticket.id),
            "ticket_no": ticket.ticket_no,
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "lifecycle_stage": ticket_lifecycle_stage(ticket.status, ticket.decision_status),
        },
    )
    db.flush()
    return {
        "ok": True,
        "ticket_id": int(ticket.id),
        "lifecycle_stage": ticket_lifecycle_stage(ticket.status, ticket.decision_status),
        "lifecycle_label": ticket_lifecycle_payload(ticket.status, ticket.decision_status).get(
            "lifecycle_label"
        ),
        "message_id": int(assistant_msg.id or 0),
        "action_id": int(action.id or 0),
        "team_ok": bool(team_ok),
    }


