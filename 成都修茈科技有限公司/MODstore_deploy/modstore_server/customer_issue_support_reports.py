# mypy: disable-error-code="arg-type, assignment"
"""Append authenticated support context without replacing original ticket evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.customer_issue_intake import enqueue_issue
from modstore_server.customer_service_tools import audit, json_dumps, json_loads
from modstore_server.models import User
from modstore_server.models_cs import CustomerServiceTicket


def record_support_report(
    db: Session,
    ticket: CustomerServiceTicket,
    *,
    owner: User,
    values: dict[str, Any],
    request_digest: str,
) -> bool:
    previous = str(ticket.evidence_json)
    evidence = json_loads(previous, {})
    context_keys = {
        "support_bundle_sha256",
        "support_bundle_base64",
        "customer_instance_id",
        "product_version",
        "git_sha",
        "installed_version",
    }
    same_issue = (
        values.get("source") == "customer_feedback"
        and bool(values.get("work_order_id"))
        and all(
            evidence.get(key, "") == value
            for key, value in values.items()
            if key not in context_keys
        )
    )
    if evidence.get("intake_request_sha256") != request_digest and not same_issue:
        raise HTTPException(409, "相同需求标识已绑定其他内容，请使用新的 source_ref")
    report = {key: values[key] for key in context_keys}
    reports = evidence.get("support_reports", [])
    saved = report == {key: evidence.get(key, "") for key in context_keys} or any(
        all(item.get(key, "") == value for key, value in report.items()) for item in reports
    )
    if values.get("support_bundle_base64") and same_issue and not saved:
        if ticket.status in {"resolved", "closed", "done", "rejected"}:
            raise HTTPException(409, "原工单已关闭，请先通过客户复验入口重开")
        revision = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
        evidence["support_reports"] = [
            *reports,
            {**report, "received_at": datetime.now(UTC).isoformat()},
        ]
        changed = (
            db.query(CustomerServiceTicket)
            .filter_by(id=ticket.id, user_id=int(owner.id), evidence_json=previous)
            .update({"evidence_json": json_dumps(evidence)}, synchronize_session=False)
        )
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "工单已有并发补报，请重试同一请求")
        db.refresh(ticket)
        event_id = enqueue_issue(db, ticket, revision=revision, support_report=report)
        audit(
            db,
            event_type="issue_support_report",
            ticket_id=ticket.id,
            session_id=ticket.session_id,
            actor=owner,
            detail={"support_bundle_sha256": report["support_bundle_sha256"], "event_id": event_id},
        )
        db.commit()
        db.refresh(ticket)
        saved = True
    return saved
