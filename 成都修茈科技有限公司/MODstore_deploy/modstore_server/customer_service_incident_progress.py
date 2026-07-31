"""Customer-service incident progress application (extracted for source-governance)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modstore_server.customer_service_tools import (
    audit,
    build_action,
    enqueue_customer_service_event,
    json_dumps,
    json_loads,
)
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceDecision,
    CustomerServiceMessage,
    CustomerServiceTicket,
)


def _summarize_incident_team_rows(team_rows: list[Dict[str, Any]]) -> str:
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


TICKET_LIFECYCLE_STEPS: tuple[tuple[int, str], ...] = (
    (1, "已收到"),
    (2, "处理中"),
    (3, "有结果"),
    (4, "待补充"),
    (5, "已完成"),
)


def ticket_lifecycle_stage(
    status: str | None = None,
    decision_status: str | None = None,
) -> int:
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


def ticket_lifecycle_payload(
    status: str | None = None,
    decision_status: str | None = None,
) -> Dict[str, Any]:
    stage = ticket_lifecycle_stage(status, decision_status)
    label = next((name for num, name in TICKET_LIFECYCLE_STEPS if num == stage), "已收到")
    return {
        "lifecycle_stage": stage,
        "lifecycle_label": label,
        "lifecycle_steps": [
            {
                "stage": num,
                "label": name,
                "state": ("done" if num < stage else "current" if num == stage else "todo"),
            }
            for num, name in TICKET_LIFECYCLE_STEPS
        ],
    }


def ticket_payload(row: CustomerServiceTicket) -> Dict[str, Any]:
    life = ticket_lifecycle_payload(row.status, row.decision_status)
    evidence = json_loads(row.evidence_json, {})
    if not isinstance(evidence, dict):
        evidence = {}
    domain = str(evidence.get("issue_domain") or "").strip().lower()
    if domain not in ISSUE_DOMAINS:
        domain = ""
    return {
        "id": row.id,
        "session_id": row.session_id,
        "ticket_no": row.ticket_no,
        "title": row.title,
        "intent": row.intent,
        "issue_domain": domain or None,
        "issue_domain_label": evidence.get("issue_domain_label")
        or ISSUE_DOMAIN_LABELS.get(domain)
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
