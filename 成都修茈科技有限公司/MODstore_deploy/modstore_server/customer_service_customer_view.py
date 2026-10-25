"""客户侧工单视图：只按白名单输出，内部审计/派单原文、执行器报错一律不给客户。

管理端（is_admin）仍走完整 payload；本模块只用于客户身份的响应。
"""

from __future__ import annotations

import re
from typing import Any

# 命中即整段替换成客户话术：本机路径、仓库地址、执行器/堆栈报错、备份表名。
INTERNAL_TEXT_RE = re.compile(
    r"/Users/|/home/\w|/root/|/opt/|[A-Za-z]:\\|git clone|git@|github\.com|\.git\b|"
    r"Cursor Agent|Command failed|Traceback|File \"|e2e-agent|report-only|执行器|"
    r"bak_\w+|备份表",
    re.I,
)
SAFE_PROGRESS = "处理过程中遇到内部问题，值班人员正在继续跟进。"
SAFE_FAILURE = "处理暂未成功，值班人员正在继续跟进。"
SAFE_REPLY = "我是小C。工单已有处理进展，值班人员正在继续跟进；如需补充，可直接发送截图或具体页面。"
TICKET_KEYS = (
    "id", "user_id", "session_id", "ticket_no", "title", "intent", "issue_domain",
    "issue_domain_label", "subject_type", "subject_id", "status", "priority", "summary",
    "decision_status", "created_at", "updated_at", "closed_at", "expected_completion_at", "lifecycle_stage",
    "lifecycle_label", "lifecycle_steps",
)  # fmt: skip
EVIDENCE_KEYS = ("source_ref", "issue_domain", "issue_domain_label", "reason")
INTENT_KEYS = (
    "intent",
    "need_ticket",
    "confidence",
    "issue_domain",
    "issue_domain_label",
    "triage_lane",
)
DECISION_KEYS = ("id", "ticket_id", "intent", "decision", "rationale", "created_at")
CARD_KEYS = (
    "type", "title", "ticket_no", "status", "intent", "subject_type", "subject_id",
    "decision", "rationale", "lifecycle_stage", "lifecycle_label", "lifecycle_steps",
)  # fmt: skip
# 客户能理解的业务动作；员工派单只告诉客户「有人跟进」，不给状态和执行结果。
BUSINESS_ACTIONS = frozenset(
    {
        "refund.apply",
        "catalog.complaint.create",
        "catalog.compliance.review",
        "llm.model_capability.propose",
    }
)


def customer_text(value: Any, fallback: str = SAFE_PROGRESS) -> str:
    text = str(value or "")
    return fallback if INTERNAL_TEXT_RE.search(text) else text


def _pick(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: row[k] for k in keys if k in row} if isinstance(row, dict) else {}


def customer_ticket(ticket: Any) -> dict[str, Any]:
    out = _pick(ticket, TICKET_KEYS)
    evidence = ticket.get("evidence") if isinstance(ticket, dict) else None
    evidence = evidence if isinstance(evidence, dict) else {}
    out["evidence"] = _pick(evidence, EVIDENCE_KEYS)
    out["progress"] = [
        {"at": r.get("at") or "", "text": customer_text(r.get("progress"))}
        for r in evidence.get("employee_reports") or []
        if isinstance(r, dict) and r.get("progress")
    ][-10:]
    return out


def customer_actions(actions: Any) -> list[dict[str, Any]]:
    out = []
    for row in actions if isinstance(actions, list) else []:
        kind = str((row or {}).get("action_type") or "") if isinstance(row, dict) else ""
        if kind in BUSINESS_ACTIONS:
            out.append(_pick(row, ("id", "action_type", "status", "created_at")))
        elif kind == "employee.dispatch":
            out.append(_pick(row, ("id", "action_type", "created_at")))
    return out


def customer_decision(decision: Any) -> dict[str, Any] | None:
    return _pick(decision, DECISION_KEYS) if isinstance(decision, dict) else None


def customer_cards(cards: Any) -> list[dict[str, Any]]:
    out = []
    for card in cards if isinstance(cards, list) else []:
        view = _pick(card, CARD_KEYS)
        if isinstance(card, dict) and "items" in card:
            view["items"] = customer_actions(card["items"])
        if view:
            out.append(view)
    return out


def customer_message_payload(payload: Any, role: str = "assistant") -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    out: dict[str, Any] = _pick(payload, ("customer_decision",))
    if role == "user" and "context" in payload:
        out["context"] = payload["context"]
    if isinstance(payload.get("ticket"), dict):
        out["ticket"] = customer_ticket(payload["ticket"])
    if "decision" in payload:
        out["decision"] = customer_decision(payload["decision"])
    for key, view in (("actions", customer_actions), ("cards", customer_cards)):
        if key in payload:
            out[key] = view(payload[key])
    return out


def customer_message(message: dict[str, Any]) -> dict[str, Any]:
    role = str(message.get("role") or "")
    content = message.get("content")
    return {
        **message,
        "content": content if role == "user" else customer_text(content, SAFE_REPLY),
        "payload": customer_message_payload(message.get("payload"), role),
    }


def customer_chat_result(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    if isinstance(result.get("intent"), dict):
        out["intent"] = _pick(result["intent"], INTENT_KEYS)
    if isinstance(result.get("ticket"), dict):
        out["ticket"] = customer_ticket(result["ticket"])
    if isinstance(result.get("message"), dict):
        out["message"] = customer_message(result["message"])
    out["decision"] = customer_decision(result.get("decision"))
    out["actions"] = customer_actions(result.get("actions"))
    out["cards"] = customer_cards(result.get("cards"))
    return out


def customer_issue(row: dict[str, Any]) -> dict[str, Any]:
    latest = row.get("latest_result")
    return {
        **row,
        "latest_result": (
            {"progress": customer_text(latest.get("progress")), "at": latest.get("at")}
            if isinstance(latest, dict)
            else None
        ),
        "last_error": SAFE_FAILURE if row.get("last_error") else "",
    }


def customer_ticket_row(row: Any) -> dict[str, Any]:
    from modstore_server.customer_service_orchestrator import ticket_payload

    return customer_ticket(ticket_payload(row))


def customer_issue_row(row: Any) -> dict[str, Any]:
    from modstore_server.customer_service_orchestrator import customer_issue_payload

    return customer_issue(customer_issue_payload(row))
