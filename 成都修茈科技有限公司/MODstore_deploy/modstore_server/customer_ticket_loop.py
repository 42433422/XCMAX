"""工单闭环：派单、工具链、审批、二次核对和关单条件。

核验只证明第二次读取和前序工具结果一致。画面有没有恢复、余额有没有到账，
不能靠文案结案。账户类停在人工核对，客户确认只在软件或工具链核验通过后生效。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from modstore_server.customer_service_tools import (
    audit,
    build_action,
    execute_action,
    json_dumps,
    json_loads,
)
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceAuditLog,
    CustomerServiceTicket,
)

SKILLS = {
    "emp.software": frozenset({"software"}),
    "emp.ai_tools": frozenset({"ai_tool"}),
    "emp.account": frozenset({"account"}),
}
TOOLS = {
    "emp.software": frozenset(
        {
            "ticket.assign",
            "ticket.read",
            "ticket.observe_status",
            "ticket.diagnose",
            "ticket.report_diagnosis",
            "ticket.verify",
            "ticket.apply_change",
        }
    ),
    "emp.ai_tools": frozenset(
        {
            "ticket.assign",
            "ticket.read",
            "ticket.observe_status",
            "tool.registry",
            "ticket.diagnose",
            "ticket.report_diagnosis",
            "ticket.verify",
            "ticket.apply_change",
        }
    ),
    "emp.account": frozenset(
        {
            "ticket.assign",
            "ticket.read",
            "ticket.observe_status",
            "account.lookup",
            "ticket.verify",
        }
    ),
}
LANE_EMPLOYEE = {
    "software": "emp.software",
    "ai_tool": "emp.ai_tools",
    "account": "emp.account",
}
HOOKS: dict[str, Any] = {
    "offline": set(),
    "pause_after": "",
    "stale": False,
    "fail_verify": False,
}
_TERMINAL = frozenset({"awaiting_customer", "needs_human", "closed"})
_SENSITIVE = ("删除", "修改配置", "写入数据")


def reset_hooks() -> None:
    HOOKS["offline"].clear()
    HOOKS["pause_after"] = ""
    HOOKS["stale"] = False
    HOOKS["fail_verify"] = False


def employee_can(employee_id: str, tool: str) -> bool:
    return tool in TOOLS.get(employee_id, frozenset())


def employee_lane(employee_id: str, lane: str) -> bool:
    return lane in SKILLS.get(employee_id, frozenset())


def lane_for(intent: str, text: str) -> str:
    if intent == "account_support":
        return "account"
    if any(mark in text for mark in ("工具调用", "无法调用", "调用失败")):
        return "ai_tool"
    return "software"


def apply_loop_status(ticket: CustomerServiceTicket) -> None:
    if ticket.closed_at:
        return
    loop = _loop(ticket)
    state = str(loop.get("state") or "")
    mapped = {
        "dispatch_failed": "pending_assignment",
        "waiting_approval": "waiting_approval",
        "failed": "failed",
        "needs_human": "waiting_user",
        "awaiting_customer": "processing",
        "processing": "processing",
        "reopened": "processing",
    }.get(state)
    if mapped:
        if (
            mapped == "processing"
            and not ticket.assigned_admin_id
            and str(ticket.status or "") in {"", "open", "pending", "queued"}
        ):
            return
        ticket.status = mapped


def run_ticket_loop(
    db: Session,
    ticket: CustomerServiceTicket,
    user: Any,
    *,
    decision_id: int | None = None,
    reschedule: bool = False,
    after_approval: bool = False,
) -> list[CustomerServiceAction]:
    evidence, loop = _load(ticket)
    state = str(loop.get("state") or "")
    if state in _TERMINAL or (state == "failed" and not after_approval):
        return _actions(db, ticket.id)
    if state == "dispatch_failed" and not reschedule:
        return _actions(db, ticket.id)
    if state == "waiting_approval" and not after_approval:
        return _actions(db, ticket.id)
    if HOOKS["stale"] and loop.get("started_at") and state == "processing":
        mark_loop_timed_out(db, ticket, user)
        return _actions(db, ticket.id)
    text = f"{ticket.summary or ''} {ticket.title or ''}"
    lane = str(loop.get("lane") or lane_for(ticket.intent or "", text))
    employee_id = str(loop.get("employee_id") or LANE_EMPLOYEE[lane])
    if reschedule:
        if employee_id in HOOKS["offline"]:
            return _actions(db, ticket.id)
        loop["attempt"] = int(loop.get("attempt") or 1) + 1
        _event(loop, "rescheduled", employee_id)
    if not loop.get("task_id"):
        loop = {
            "task_id": f"TSK{int(ticket.id):08d}",
            "lane": lane,
            "employee_id": employee_id,
            "attempt": 1,
            "state": "processing",
            "started_at": datetime.now(UTC).isoformat(),
            "verified": False,
            "timeline": [],
            "supplements": [],
        }
        _event(loop, "received", employee_id)
    if after_approval and str(loop.get("state") or "") == "waiting_approval":
        loop["state"] = "processing"
        _event(loop, "approved", employee_id)
    loop["lane"] = lane
    loop["employee_id"] = employee_id
    sensitive = any(mark in text for mark in _SENSITIVE)
    for step in _steps(lane, sensitive):
        action = _run_step(db, ticket, user, loop, step, decision_id=decision_id)
        if action.status == "waiting_approval":
            _finish(
                ticket,
                evidence,
                loop,
                "waiting_approval",
                _conclusion("waiting_approval"),
                False,
            )
            db.flush()
            return _actions(db, ticket.id)
        if action.status != "completed":
            code = str(json_loads(action.result_json, {}).get("code") or "")
            failed = "dispatch_failed" if code == "employee_offline" else "failed"
            _finish(ticket, evidence, loop, failed, _conclusion(failed), False)
            db.flush()
            return _actions(db, ticket.id)
        if HOOKS["pause_after"] == step:
            _finish(ticket, evidence, loop, "processing", "工具链暂停，工单未关闭。", False)
            db.flush()
            return _actions(db, ticket.id)
    verified = _verified(db, ticket.id)
    if lane == "account":
        _finish(ticket, evidence, loop, "needs_human", _conclusion("needs_human"), False)
    elif verified:
        current = evidence.get("resolution")
        resolution = current if isinstance(current, dict) else {}
        resolution["state"] = "awaiting_customer_verification"
        evidence["resolution"] = resolution
        _finish(ticket, evidence, loop, "awaiting_customer", _conclusion(lane), True)
    else:
        _finish(ticket, evidence, loop, "failed", _conclusion("failed"), False)
    db.flush()
    return _actions(db, ticket.id)


def resume_ticket_loop(db: Session, ticket: CustomerServiceTicket, user: Any) -> dict[str, Any]:
    loop = _loop(ticket)
    if str(loop.get("state") or "") != "dispatch_failed":
        return {"ok": False, "reason": "not_waiting"}
    employee_id = str(loop.get("employee_id") or "")
    if employee_id in HOOKS["offline"]:
        return {"ok": False, "reason": "still_offline"}
    before = len(_actions(db, ticket.id))
    run_ticket_loop(db, ticket, user, reschedule=True)
    db.flush()
    return {"ok": True, "created": len(_actions(db, ticket.id)) - before}


def approve_ticket_loop(
    db: Session, ticket: CustomerServiceTicket, user: Any, approval_id: str
) -> dict[str, Any]:
    action = (
        db.query(CustomerServiceAction)
        .filter(
            CustomerServiceAction.ticket_id == ticket.id,
            CustomerServiceAction.action_type == "ticket.apply_change",
            CustomerServiceAction.status == "waiting_approval",
        )
        .order_by(CustomerServiceAction.id.desc())
        .first()
    )
    if action is None:
        return {"changed": False}
    request = json_loads(action.request_json, {})
    before = action.result_json
    request["approval"] = {"id": approval_id, "decision": "approved"}
    action.request_json = json_dumps(request)
    execute_action(db, action, user)
    if action.status == "completed":
        run_ticket_loop(db, ticket, user, after_approval=True)
    elif action.status != "pending_execution":
        return {"changed": False, "status": action.status, "result": action.result_json}
    db.flush()
    return {"changed": True, "result": action.result_json, "previous": before}


def mark_loop_timed_out(db: Session, ticket: CustomerServiceTicket, user: Any) -> bool:
    evidence, loop = _load(ticket)
    if not loop.get("task_id") or str(loop.get("state") or "") in _TERMINAL | {"failed"}:
        return False
    before = len(_actions(db, ticket.id))
    _event(loop, "timed_out", str(loop.get("employee_id") or ""))
    _finish(ticket, evidence, loop, "failed", "处理超时，未关闭工单，已有记录保留。", False)
    audit(
        db,
        event_type="ticket_loop_timeout",
        ticket_id=ticket.id,
        actor=user,
        detail={"task_id": loop.get("task_id"), "kept_actions": before},
    )
    db.flush()
    return len(_actions(db, ticket.id)) == before


def recover_ticket_loop(db: Session, ticket: CustomerServiceTicket, user: Any) -> list[Any]:
    if HOOKS["stale"]:
        mark_loop_timed_out(db, ticket, user)
        return _actions(db, ticket.id)
    return run_ticket_loop(db, ticket, user)


def record_supplement(
    db: Session,
    ticket: CustomerServiceTicket,
    user: Any,
    note: str,
    attachment: str = "",
) -> dict[str, Any]:
    text = str(note or "").strip()
    name = str(attachment or "").strip()
    if len(text) < 4:
        return {"ok": False, "reason": "note_too_short"}
    if name and (".." in name or "/" in name or "\\" in name):
        return {"ok": False, "reason": "illegal_attachment"}
    evidence, loop = _load(ticket)
    if not loop.get("task_id"):
        loop = {
            "task_id": f"TSK{int(ticket.id):08d}",
            "state": str(loop.get("state") or "processing"),
            "timeline": [],
            "supplements": [],
        }
    supplements = [item for item in loop.get("supplements") or [] if isinstance(item, dict)]
    supplements.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "note": text[:500],
            "attachment": name[:120],
            "user_id": int(getattr(user, "id", 0) or 0),
        }
    )
    loop["supplements"] = supplements[-20:]
    employee_id = str(loop.get("employee_id") or "")
    loop["notified_employee_id"] = employee_id
    _event(loop, "supplemented", employee_id)
    evidence["loop"] = loop
    evidence["loop_public"] = _public(loop)
    ticket.evidence_json = json_dumps(evidence)
    audit(
        db,
        event_type="ticket_supplemented",
        ticket_id=ticket.id,
        actor=user,
        detail={"employee_id": employee_id, "task_id": loop.get("task_id")},
    )
    db.flush()
    return {"ok": True, "task_id": loop.get("task_id"), "employee_id": employee_id}


def note_customer_decision(evidence: dict[str, Any], decision: str) -> None:
    loop = evidence.get("loop")
    if not isinstance(loop, dict) or not loop.get("task_id"):
        return
    if decision == "resolved":
        loop["state"] = "closed"
        loop["verified"] = True
        loop["conclusion"] = "你已确认本次处理，工单关闭。历史工具记录仍保留。"
    elif decision == "reopen":
        loop["state"] = "reopened"
        loop["verified"] = False
        loop["conclusion"] = "你反馈问题仍在，工单已重新打开，尚未结案。"
    _event(loop, decision, str(loop.get("employee_id") or ""))
    evidence["loop"] = loop
    evidence["loop_public"] = _public(loop)


def export_ticket_audit(db: Session, ticket: CustomerServiceTicket) -> dict[str, Any]:
    loop = _loop(ticket)
    actions = _actions(db, ticket.id)
    logs = (
        db.query(CustomerServiceAuditLog)
        .filter(CustomerServiceAuditLog.ticket_id == ticket.id)
        .order_by(CustomerServiceAuditLog.id.asc())
        .all()
    )
    return {
        "ticket_id": int(ticket.id),
        "ticket_no": ticket.ticket_no,
        "task_id": loop.get("task_id"),
        "employee_id": loop.get("employee_id"),
        "state": loop.get("state"),
        "timeline": list(loop.get("timeline") or []),
        "actions": [
            {
                "id": int(row.id),
                "action_type": row.action_type,
                "status": row.status,
                "user_id": row.user_id,
            }
            for row in actions
        ],
        "audits": [
            {
                "id": int(row.id),
                "event_type": row.event_type,
                "actor_user_id": row.actor_user_id,
                "actor_type": row.actor_type,
                "at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in logs
        ],
    }


def _steps(lane: str, sensitive: bool) -> list[str]:
    if lane == "account":
        steps = [
            "ticket.assign",
            "ticket.read",
            "ticket.observe_status",
            "account.lookup",
            "ticket.verify",
        ]
    elif lane == "ai_tool":
        steps = [
            "ticket.assign",
            "ticket.read",
            "ticket.observe_status",
            "tool.registry",
            "ticket.diagnose",
            "ticket.report_diagnosis",
            "ticket.verify",
        ]
    else:
        steps = [
            "ticket.assign",
            "ticket.read",
            "ticket.observe_status",
            "ticket.diagnose",
            "ticket.report_diagnosis",
            "ticket.verify",
        ]
    if sensitive and lane != "account":
        steps.insert(-1, "ticket.apply_change")
    return steps


def _run_step(
    db: Session,
    ticket: CustomerServiceTicket,
    user: Any,
    loop: dict[str, Any],
    step: str,
    *,
    decision_id: int | None,
) -> CustomerServiceAction:
    employee_id = str(loop.get("employee_id") or "")
    target = _target(ticket, loop, step)
    request = _request(db, ticket, loop, step)
    action = build_action(
        db,
        ticket_id=int(ticket.id),
        decision_id=decision_id,
        user_id=int(getattr(user, "id", 0) or 0),
        action_type=step,
        target_type="ticket",
        target_id=target,
        request=request,
    )
    already_done = action.status in {"completed", "waiting_approval"}
    if not already_done:
        execute_action(db, action, user)
    if action.status == "completed" and not already_done:
        _event(loop, step, employee_id)
    return action


def _target(ticket: CustomerServiceTicket, loop: dict[str, Any], step: str) -> str:
    if step == "ticket.assign":
        return f"{loop.get('employee_id')}:{int(loop.get('attempt') or 1)}"
    if step == "ticket.apply_change":
        return "gated"
    if step == "tool.registry":
        return "published"
    if step == "account.lookup":
        return str(ticket.user_id)
    return str(ticket.ticket_no or ticket.id)


def _request(
    db: Session, ticket: CustomerServiceTicket, loop: dict[str, Any], step: str
) -> dict[str, Any]:
    employee_id = str(loop.get("employee_id") or "")
    body: dict[str, Any] = {
        "ticket_id": int(ticket.id),
        "user_id": int(ticket.user_id or 0),
        "employee_id": employee_id,
        "lane": loop.get("lane"),
        "online": employee_id not in HOOKS["offline"],
    }
    if step == "ticket.observe_status":
        body["ticket_no"] = _result(db, ticket.id, "ticket.read").get("ticket_no")
    if step == "ticket.report_diagnosis":
        body["ticket_no"] = _result(db, ticket.id, "ticket.diagnose").get("ticket_no")
    if step == "ticket.verify":
        source = "ticket.report_diagnosis" if loop.get("lane") != "account" else "account.lookup"
        prior = _result(db, ticket.id, source) or _result(db, ticket.id, "ticket.read")
        body["ticket_no"] = prior.get("ticket_no") or ticket.ticket_no
        body["intent"] = ticket.intent
        body["fail_verify"] = bool(HOOKS["fail_verify"])
    if step == "ticket.apply_change":
        body["change"] = {"requested": "gated"}
    return body


def _result(db: Session, ticket_id: int, action_type: str) -> dict[str, Any]:
    row = (
        db.query(CustomerServiceAction)
        .filter(
            CustomerServiceAction.ticket_id == ticket_id,
            CustomerServiceAction.action_type == action_type,
            CustomerServiceAction.status == "completed",
        )
        .order_by(CustomerServiceAction.id.desc())
        .first()
    )
    parsed = json_loads(row.result_json, {}) if row else {}
    return parsed if isinstance(parsed, dict) else {}


def _verified(db: Session, ticket_id: int) -> bool:
    parsed = _result(db, ticket_id, "ticket.verify")
    return parsed.get("matched") is True and parsed.get("executed") is True


def _finish(
    ticket: CustomerServiceTicket,
    evidence: dict[str, Any],
    loop: dict[str, Any],
    state: str,
    conclusion: str,
    verified: bool,
) -> None:
    loop["state"] = state
    loop["verified"] = verified
    loop["conclusion"] = conclusion
    _event(loop, state, str(loop.get("employee_id") or ""))
    evidence["loop"] = loop
    evidence["loop_public"] = _public(loop)
    ticket.evidence_json = json_dumps(evidence)
    apply_loop_status(ticket)


def _conclusion(state: str) -> str:
    return {
        "software": "已再次读取工单，并与诊断记录一致。请你确认画面是否恢复，系统尚未结案。",
        "ai_tool": "已核对工具注册和调用权限，记录与第二次读取一致。系统尚未结案。",
        "needs_human": "已读取账户记录，未修改余额或充值。到账需要人工核对账单，系统尚未结案。",
        "failed": "核验未通过，工单保持未关闭。",
        "dispatch_failed": "负责员工暂不可用，工单停在待派单，没有丢弃。",
        "waiting_approval": "有写入操作等待审批，审批前不会执行。",
    }.get(state, "工单仍在处理，系统尚未结案。")


def _event(loop: dict[str, Any], name: str, employee_id: str) -> None:
    timeline = [item for item in loop.get("timeline") or [] if isinstance(item, dict)]
    timeline.append(
        {
            "seq": len(timeline) + 1,
            "event": name,
            "employee_id": employee_id,
            "at": datetime.now(UTC).isoformat(),
        }
    )
    loop["timeline"] = timeline[-80:]


def _public(loop: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": loop.get("task_id"),
        "employee_id": loop.get("employee_id"),
        "state": loop.get("state"),
        "verified": bool(loop.get("verified")),
        "conclusion": loop.get("conclusion") or "",
    }


def _load(ticket: CustomerServiceTicket) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = json_loads(ticket.evidence_json, {})
    if not isinstance(evidence, dict):
        evidence = {}
    loop = evidence.get("loop")
    return evidence, dict(loop) if isinstance(loop, dict) else {}


def _loop(ticket: CustomerServiceTicket) -> dict[str, Any]:
    return _load(ticket)[1]


def _actions(db: Session, ticket_id: int) -> list[CustomerServiceAction]:
    return (
        db.query(CustomerServiceAction)
        .filter(CustomerServiceAction.ticket_id == ticket_id)
        .order_by(CustomerServiceAction.id.asc())
        .all()
    )
