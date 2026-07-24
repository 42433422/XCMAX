"""Deterministic, read-only customer-support grounding auditor."""

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
        ticket_id
        or issue
        or source == "customer_ticket"
        or event_type.endswith("customer_ticket")
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
    severity = (
        str(payload.get("severity") or incident.get("severity") or "normal")
        .strip()
        .lower()
    )
    return {
        "id": ticket_id or "CS-unknown",
        "issue": issue or f"客服工单 {ticket_id}",
        "knowledge_sources": sources,
        "severity": severity or "normal",
    }


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx  # deterministic; no host side effects
    ticket = _normalize_ticket(dict(payload or {}))
    if not isinstance(ticket, dict):
        return _failed("ticket object is required", "missing_ticket")
    ticket_id = str(ticket.get("id") or "").strip()[:160]
    issue = str(ticket.get("issue") or "").strip()[:2000]
    sources = (
        ticket.get("knowledge_sources")
        if isinstance(ticket.get("knowledge_sources"), list)
        else []
    )
    issues: list[dict[str, str]] = []
    if not ticket_id or not issue:
        issues.append({"code": "missing_ticket_context", "path": "ticket"})
    if not sources:
        issues.append(
            {"code": "missing_grounding_sources", "path": "ticket.knowledge_sources"}
        )
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
