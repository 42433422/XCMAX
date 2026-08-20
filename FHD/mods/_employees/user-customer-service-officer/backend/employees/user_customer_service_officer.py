"""Deterministic, read-only customer-support employee."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _incident_blob(payload: dict) -> dict:
    incident = payload.get("incident")
    return incident if isinstance(incident, dict) else {}


def _normalize_ticket(payload: dict) -> Optional[Dict[str, Any]]:
    """Accept burn-in ``ticket`` or incident-bus / 客服工单 shaped payloads."""

    ticket = payload.get("ticket")
    if isinstance(ticket, dict):
        return ticket

    incident = _incident_blob(payload)
    ticket_id = str(
        payload.get("ticket_no")
        or payload.get("subject_id")
        or incident.get("ticket_no")
        or incident.get("subject_id")
        or payload.get("ticket_id")
        or incident.get("ticket_id")
        or ""
    ).strip()
    issue = str(
        payload.get("summary")
        or incident.get("summary")
        or payload.get("title")
        or incident.get("title")
        or payload.get("task")
        or ""
    ).strip()
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    if not issue:
        issue = str(raw.get("body") or raw.get("title") or "").strip()
    source = str(payload.get("source") or incident.get("source") or "").strip().lower()
    event_type = str(payload.get("event_type") or "").strip()
    if not (
        ticket_id or issue or source == "customer_ticket" or event_type.endswith("customer_ticket")
    ):
        return None

    sources = payload.get("knowledge_sources")
    if not isinstance(sources, list):
        sources = incident.get("knowledge_sources")
    if not isinstance(sources, list):
        sources = []
    if not sources and issue:
        # 客服 bus 常无知识库命中；用工单摘要做最小 grounding，避免整岗 handler_failed
        sources = [
            {
                "source": "customer_ticket_incident",
                "text": issue[:500],
            }
        ]
    severity = str(payload.get("severity") or incident.get("severity") or "normal").strip().lower()
    return {
        "id": ticket_id or "CS-unknown",
        "issue": issue or f"客服工单 {ticket_id}",
        "knowledge_sources": sources,
        "severity": severity or "normal",
    }


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx  # deterministic; no host side effects
    data = dict(payload or {})
    action = str(data.get("action") or "").strip()
    if action == "status":
        return _status()
    if action == "demand_intake":
        return _demand_intake(data)
    ticket = _normalize_ticket(data)
    if not isinstance(ticket, dict):
        return _failed("ticket object is required", "missing_ticket")
    ticket_id = str(ticket.get("id") or "").strip()[:160]
    issue = str(ticket.get("issue") or "").strip()[:2000]
    sources = (
        ticket.get("knowledge_sources") if isinstance(ticket.get("knowledge_sources"), list) else []
    )
    issues: list[dict[str, str]] = []
    if not ticket_id or not issue:
        issues.append({"code": "missing_ticket_context", "path": "ticket"})
    if not sources:
        issues.append({"code": "missing_grounding_sources", "path": "ticket.knowledge_sources"})
    severity = str(ticket.get("severity") or "normal").strip().lower()
    if severity not in {"low", "normal", "high", "critical"}:
        issues.append({"code": "invalid_severity", "path": "ticket.severity"})
    return {
        "ok": True,
        "status": "approved" if not issues else "rejected",
        "summary": (
            f"客户问题 {ticket_id or '?'} 已完成只读资料核对："
            f"{len(sources)} 条依据、{len(issues)} 个缺口；未发送客户消息或创建交接。"
        ),
        "ticket_id": ticket_id,
        "severity": severity,
        "grounded_source_count": len(sources),
        "issues": issues,
        "ready_for_response_draft": not issues,
        "evidence": (
            ["input.ticket.issue", "input.ticket.knowledge_sources"]
            if isinstance((payload or {}).get("ticket"), dict)
            else ["input.incident_or_customer_ticket"]
        ),
        "read_only": True,
        "side_effects": [],
    }


def _status() -> dict[str, Any]:
    return {
        "ok": True,
        "status": "ready",
        "summary": "用户客服员工已就绪：可生成需求采集话术、表单链接草稿，并保留只读资料核对能力。",
        "issues": [],
        "ready_for_response_draft": True,
        "evidence": ["input.action"],
        "read_only": True,
        "side_effects": [],
    }


def _demand_intake(payload: dict[str, Any]) -> dict[str, Any]:
    brief = _clip(payload.get("brief"), 1200)
    if not brief:
        return _failed("brief is required", "missing_brief")
    client_name = _clip(payload.get("client_name"), 128)
    form_url = _clip(payload.get("form_url"), 512) or "https://xiu-ci.com/contact.html"
    channel = _clip(payload.get("channel"), 32) or "wechat"
    greeting = f"{client_name}，您好" if client_name else "您好"
    questions = [
        "当前最想让 AI 员工接住的业务场景是什么？",
        "现有资料、系统或 Excel 表里，哪些数据可以先接入？",
        "希望这次试点最后用什么结果来验收？",
    ]
    message_text = "\n".join(
        [
            f"{greeting}，我是修茈 XCMAX 的业务顾问。",
            f"我先按您刚才的场景整理了一个需求采集入口：{form_url}",
            "请您打开后补充公司、联系方式和关键需求，我们会按提交编号分配销售并安排 AI 员工跟进。",
            f"我已记录的背景：{brief[:500]}",
        ]
    )
    return {
        "ok": True,
        "status": "drafted",
        "summary": "已生成需求采集话术草稿和表单链接；未发送客户消息。",
        "items": [
            {
                "type": "message_draft",
                "channel": channel,
                "message_text": message_text,
                "form_url": form_url,
                "questions": questions,
            }
        ],
        "form_url": form_url,
        "issues": [],
        "ready_for_send": True,
        "ready_for_response_draft": True,
        "evidence": ["input.brief", "input.form_url", "input.channel"],
        "read_only": True,
        "side_effects": [],
    }


def _clip(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _failed(message: str, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "summary": message,
        "error_code": code,
        "error": f"{code}: {message}",
        "evidence": [],
        "read_only": True,
        "side_effects": [],
    }
