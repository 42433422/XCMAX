"""Deterministic, read-only customer-support grounding auditor."""

from __future__ import annotations

from typing import Any


def run(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    ticket = dict(payload or {}).get("ticket")
    if not isinstance(ticket, dict):
        return _failed("ticket object is required", "missing_ticket")
    ticket_id = str(ticket.get("id") or "").strip()[:160]
    issue = str(ticket.get("issue") or "").strip()[:2000]
    sources = ticket.get("knowledge_sources") if isinstance(ticket.get("knowledge_sources"), list) else []
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
        "summary": f"客户问题 {ticket_id or '?'} 已完成只读资料核对：{len(sources)} 条依据、{len(issues)} 个缺口；未发送客户消息或创建交接。",
        "ticket_id": ticket_id,
        "severity": severity,
        "grounded_source_count": len(sources),
        "issues": issues,
        "ready_for_response_draft": not issues,
        "evidence": ["input.ticket.issue", "input.ticket.knowledge_sources"],
        "read_only": True,
        "side_effects": [],
    }


def _failed(message: str, code: str) -> dict[str, Any]:
    return {"ok": False, "status": "failed", "summary": message, "error_code": code, "evidence": [], "read_only": True, "side_effects": []}
