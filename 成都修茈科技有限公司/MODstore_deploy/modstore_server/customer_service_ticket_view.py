"""Read-only ticket presentation for API and orchestration responses.

Lifecycle and domain configuration come from the caller, without importing the
orchestration facade or performing storage/dispatch operations.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import timezone
from typing import Any

from modstore_server.customer_service_tools import json_loads
from modstore_server.customer_service_triage import ticket_taxonomy
from modstore_server.models_cs import CustomerServiceTicket


def serialize_ticket(
    row: CustomerServiceTicket,
    *,
    lifecycle: dict[str, Any],
    issue_domains: Collection[str],
    domain_labels: Mapping[str, str],
) -> dict[str, Any]:
    evidence = json_loads(row.evidence_json, {})
    if not isinstance(evidence, dict):
        evidence = {}
    domain = str(evidence.get("issue_domain") or "").strip().lower()
    if domain not in issue_domains:
        domain = ""
    expected_completion_at = getattr(row, "expected_completion_at", None)
    if expected_completion_at is not None and expected_completion_at.tzinfo is None:
        expected_completion_at = expected_completion_at.replace(tzinfo=timezone.utc)
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
        **ticket_taxonomy(
            row.intent,
            getattr(row, "submitter_type", None) or "unknown",
            evidence,
        ),
        "issue_domain": domain or None,
        "issue_domain_label": evidence.get("issue_domain_label")
        or domain_labels.get(domain)
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
        "expected_completion_at": (
            expected_completion_at.isoformat() if expected_completion_at else None
        ),
        **lifecycle,
    }
