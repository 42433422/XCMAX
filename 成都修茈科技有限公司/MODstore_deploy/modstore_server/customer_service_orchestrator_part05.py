# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
from typing import Any

from modstore_server.customer_issue_delivery_contract import (
    record_team_progress,
    team_succeeded,
)

CLOSED_CUSTOMER_ISSUE_STATES = frozenset({"resolved", "closed", "done", "rejected"})


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def ticket_lifecycle_stage(status: str | None = None, decision_status: str | None = None) -> int:
    """用户侧五阶段：1已收到 → 2处理中 → 3有结果 → 4待补充 → 5已完成。"""
    s = str(status or "").strip().lower()
    d = str(decision_status or "").strip().lower()
    if s in CLOSED_CUSTOMER_ISSUE_STATES:
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
    from modstore_server.incident_team_handler_digest import redact_text

    bits: list[str] = []
    role_cn = {"scout": "排查", "fix": "修复", "verify": "验证"}
    for row in team_rows or []:
        if not isinstance(row, dict):
            continue
        role = role_cn.get(str(row.get("role") or "").strip(), str(row.get("role") or "执行"))
        outcome = (
            "已完成" if row.get("ok") else "处理中" if row.get("status") == "pending" else "未完成"
        )
        outputs = (row.get("handler_outputs") or {}).get("outputs", [])
        details = [
            "；".join(
                str(value)
                for value in (
                    o.get("cause"),
                    o.get("summary") or o.get("output_summary"),
                    o.get("change_summary"),
                    o.get("error") or o.get("output_error"),
                )
                if value
            )
            for o in outputs
            if isinstance(o, dict)
        ]
        detail = redact_text(
            "；".join(
                [d for d in details if d]
                + (
                    [row["handler_outputs"]["poll_error"]]
                    if (row.get("handler_outputs") or {}).get("poll_error")
                    else []
                )
            )
        )
        bits.append(f"{role}{outcome}：{detail or '尚未提供原因或处理说明'}")
    return "；".join(bits[:6]) if bits else "值班员工已接手"


def _customer_incident_progress(team_rows: list[dict[str, Any]]) -> str:
    """客户可见进度只用固定客服话术：不拼接员工输出、报错原文、路径或工具名（#2389）。"""
    role_cn = {"scout": "排查", "fix": "修复", "verify": "验证"}
    bits, failed = [], False
    for row in [r for r in team_rows or [] if isinstance(r, dict)][:6]:
        role = role_cn.get(str(row.get("role") or "").strip(), "处理")
        pending = row.get("status") in ("pending", "manual_review")
        failed = failed or not (row.get("ok") or pending)
        bits.append(f"{role}{'已完成' if row.get('ok') else '处理中' if pending else '暂未完成'}")
    note = "处理过程中遇到内部问题，值班人员正在继续跟进，您无需操作" if failed else ""
    return "；".join(bits + [note] if note else bits) or "值班员工已接手"


def apply_customer_ticket_incident_progress(
    db: _facade().Session,
    *,
    ticket_id: int,
    event_id: int = 0,
    team_ok: bool = False,
    team_rows: _facade().Optional[list[_facade().Dict[str, _facade().Any]]] = None,
    summary_hint: str = "",
    executor: str = "incident_team",
) -> _facade().Dict[str, _facade().Any]:
    """把 AI 员工 / incident team 执行结果回写到已有客服工单。

    复用现有 ``CustomerServiceMessage`` / ``CustomerServiceAction`` / ``audit``，
    不新建旁路表：员工结果只推进到待正式交付，终态由客户运行回执判定。
    ``executor`` 标明重派或外部执行器（如 grok_bot），每次派单各记一条执行动作。
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
    team_ok = bool(team_ok) and team_succeeded(rows)
    from modstore_server.customer_delivery_receipts import canonical_sha256
    from modstore_server.customer_service_customer_view import customer_ticket

    progress_digest = canonical_sha256(
        {
            "event_id": int(event_id),
            "team_ok": team_ok,
            "rows": [
                {
                    key: row.get(key)
                    for key in (
                        "role",
                        "employee_id",
                        "ok",
                        "status",
                        "handler_outputs",
                    )
                }
                for row in rows
            ],
        }
    )
    if ticket.status in {"resolved", "closed"} or any(
        report.get("progress_sha256") == progress_digest
        for report in ev.get("employee_reports", [])
        if isinstance(report, dict)
    ):
        return {
            "ok": True,
            "replayed": True,
            "ticket_id": int(ticket.id),
            "team_ok": team_ok,
        }
    resolution = record_team_progress(ticket, ev, event_id=event_id, rows=rows)
    # 内部明细（含报错原文）只进 action.result_json 与审计 detail；客户消息/证据只用客服话术。
    progress = _facade()._summarize_incident_team_rows(rows)
    customer_progress = _customer_incident_progress(rows)
    progress_record = {"event_id": int(event_id or 0), "team_ok": team_ok, "progress": progress}
    customer_record = {**progress_record, "progress": customer_progress}
    hint = str(summary_hint or ticket.summary or ticket.title or "").strip()[:120]
    if team_ok:
        reply = _facade().delivery_policy.success_reply(
            hint or ticket.ticket_no, customer_progress, delivery_managed
        )
    else:
        reply = f"我是小C。工单「{hint or ticket.ticket_no}」已有员工处理进展：{customer_progress}。我们会继续跟进，也可继续补充截图或具体页面。"
    reply += "下一步：" + (
        "等待正式版本交付后，请在原工单复验并确认。"
        if team_ok
        else (
            "等待已受理任务的处理结果，请保留原工单。"
            if resolution["state"] == "processing"
            else "继续排查或转人工处理，请保留原工单。"
        )
    )
    outputs = [o for r in rows for o in (r.get("handler_outputs") or {}).get("outputs") or []]
    outputs = [o for o in outputs if isinstance(o, dict)]
    tasks = sorted({str(o.get("para_task_id") or o.get("task_id") or "") for o in outputs} - {""})
    request = {
        "event_id": int(event_id or 0),
        "team_ok": bool(team_ok),
        "roles": resolution["team"][:8],
        "para_task_ids": tasks[:8],
        "tools": sorted({str(o.get("tool_name") or "") for o in outputs} - {""}),
        "executor": executor,
    }
    tried = [t for o in outputs for t in o.get("codex_models_tried") or [] if isinstance(t, dict)]
    if tried:
        # 内部动作记录尝试过的 Codex 模型（不进客户消息）。
        request["codex_models_tried"] = tried[:8]
    # 同一派单（同一组 Para 任务）待定→终态更新同一条；重派/外部执行是新任务，另记一条。
    action = _facade().build_action(
        db,
        ticket_id=int(ticket.id),
        user_id=int(ticket.user_id or 0),
        action_type="employee.dispatch",
        target_type="incident_team",
        target_id=f"{event_id or ''}:{','.join(tasks) or progress_digest[:16]}"[:240],
        request=request,
    )
    bad = [r for r in rows if not r.get("ok")]
    seen = {str(r.get("status")) for r in bad}
    failed = [
        str(r.get("role")) for r in bad if r.get("status") not in ("pending", "manual_review")
    ]
    # 动作状态必须与角色结果一致：角色失败不能标 completed。
    waiting = next((state for state in ("manual_review", "pending") if state in seen), "partial")
    action.status = "completed" if team_ok else "failed" if failed or not rows else waiting
    action.request_json = _facade().json_dumps(request)
    action.result_json = _facade().json_dumps({"ok": team_ok, **progress_record, **request})
    action.error = f"未成功角色：{'、'.join(failed)}" if failed else ""
    db.flush()
    _facade().delivery_policy.apply_ticket_outcome(ticket, team_ok, delivery_managed)
    if resolution["state"] == "processing":
        ticket.decision_status = "pending"
    reports = list(ev.get("employee_reports") or [])
    reports.append(
        {
            "type": "incident_team",
            "progress_sha256": progress_digest,
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "progress": customer_progress[:500],
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
                # 客户消息只存客户白名单工单视图：resolution 等内部证据不随消息落库。
                "ticket": customer_ticket(_facade().ticket_payload(ticket)),
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
                "employee_progress": customer_record,
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
        # 管理端必须用稳定的市场用户 ID 把交付工单关联到客户资料。
        "user_id": row.user_id,
        "submitter_type": getattr(row, "submitter_type", None) or "unknown",
        "assigned_admin_id": row.assigned_admin_id,
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


def customer_issue_payload(row: _facade().CustomerServiceTicket) -> dict[str, Any]:
    evidence = _facade().json_loads(row.evidence_json, {})
    resolution = evidence.get("resolution") or {}
    state = str(resolution.get("state") or "received")
    reports = [r for r in evidence.get("employee_reports") or [] if isinstance(r, dict)]
    closed = row.status in CLOSED_CUSTOMER_ISSUE_STATES
    return {
        "id": row.id,
        "ticket_no": row.ticket_no,
        "title": row.title,
        "summary": row.summary,
        "status": row.status,
        "state": state,
        "lifecycle_label": _facade().ticket_lifecycle_payload(row.status, row.decision_status)[
            "lifecycle_label"
        ],
        "latest_result": (
            {k: reports[-1].get(k) for k in ("team_ok", "progress", "at")} if reports else None
        ),
        "last_error": str(resolution.get("last_error") or ""),
        "closed_at": row.closed_at.isoformat() if row.closed_at else "",
        "reopen_count": len(evidence.get("reopen_history") or []),
        "can_resolve": not closed,
        "can_reopen": closed or state not in {"received", "reopened"},
    }
