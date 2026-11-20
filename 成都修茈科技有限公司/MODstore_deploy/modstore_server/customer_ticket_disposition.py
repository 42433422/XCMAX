# mypy: disable-error-code="arg-type, assignment"
"""Terminal triage of a report on its original customer-service conversation."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.customer_issue_delivery_contract import issue_resolution, repair_verification
from modstore_server.customer_service_tools import audit, json_dumps, json_loads
from modstore_server.customer_ticket_intake_review import (
    IntakeReview,
    NegativeIntakeConfirmation,
    parse_intake_review,
)
from modstore_server.models_cs import (
    CustomerServiceAction,
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceTicket,
)

NEGATIVE_NOTES = {
    "invalid": "你已确认这是一段演练描述，所述问题没有实际发生。",
    "out_of_scope": "你已确认此事项只涉及第三方或其他外部对象，与本平台支持的产品或服务无关。",
}
LINKED_SUPPORT_FIELDS = (
    "order_no",
    "catalog_id",
    "pkg_id",
    "artifact",
    "account_custom",
    "complaint_type",
    "provider",
    "model",
    "has_image",
    "evidence",
)


def has_linked_support_material(fields: dict[str, Any]) -> bool:
    return any(fields.get(name) for name in LINKED_SUPPORT_FIELDS)


def read_disposition(evidence: dict[str, Any]) -> dict[str, Any] | None:
    receipt = evidence.get("admin_disposition") or evidence.get("assistant_disposition")
    return receipt if isinstance(receipt, dict) else None


def prepare_disposition(
    ticket: CustomerServiceTicket, evidence: dict[str, Any], receipt: dict[str, Any], *, source: str
) -> str:
    evidence[source] = receipt
    evidence.pop("fault_remains", None)
    resolution = issue_resolution(ticket, evidence)
    resolution.update(state="rejected", closed_at=receipt["at"], **repair_verification(None))
    evidence["resolution"] = resolution
    label = "所述问题核验无效" if receipt["kind"] == "invalid" else "所述事项超出平台受理范围"
    return f"工单 {ticket.ticket_no} 已处置。{label}。{receipt['note']}"


def confirm_negative_intake(
    db: Session, session: CustomerServiceSession, confirmation: NegativeIntakeConfirmation
) -> tuple[CustomerServiceMessage, IntakeReview, str]:
    """Bind the reporter's selection to the immediately preceding assessed message."""
    messages = (
        db.query(CustomerServiceMessage)
        .filter_by(session_id=session.id, user_id=session.user_id)
        .order_by(CustomerServiceMessage.id.desc())
        .limit(2)
        .all()
    )
    conflict = HTTPException(409, "受理确认已变更，请刷新会话后核对原工单。")
    if len(messages) != 2:
        raise conflict
    assistant, original = messages
    if (
        assistant.role != "assistant"
        or assistant.ticket_id is not None
        or original.role != "user"
        or original.ticket_id is not None
        or original.id != confirmation.source_message_id
    ):
        raise conflict
    payload = json_loads(assistant.payload_json, {})
    assessment = payload.get("intake_assessment") if isinstance(payload, dict) else None
    if not isinstance(assessment, dict):
        raise conflict
    report = str(original.content or "")
    digest = hashlib.sha256(report.encode()).hexdigest()
    expected = confirmation.model_dump()
    if payload.get("intake_confirmation") != expected or assessment.get("report_sha256") != digest:
        raise conflict
    review = parse_intake_review(json_dumps(assessment.get("review")), report=report)
    if review.disposition != confirmation.kind:
        raise conflict
    return original, review, digest


def close_confirmed_intake(
    db: Session,
    ticket: CustomerServiceTicket,
    original: CustomerServiceMessage,
    confirmation: NegativeIntakeConfirmation,
    digest: str,
    *,
    now: datetime,
) -> str:
    """Close the ticket just created in this transaction and attribute it to Xiaoc."""
    evidence = json_loads(ticket.evidence_json, {})
    if (
        ticket.user_id != original.user_id
        or ticket.session_id != original.session_id
        or ticket.assigned_admin_id is not None
        or ticket.intent != "general"
        or has_linked_support_material(evidence)
    ):
        raise HTTPException(409, "原工单仍需核实，无法自动处置。")
    claimed = (
        db.query(CustomerServiceMessage)
        .filter_by(id=original.id, ticket_id=None)
        .update({"ticket_id": ticket.id}, synchronize_session="fetch")
    )
    if claimed != 1:
        raise HTTPException(409, "该反馈已提交，请刷新会话核对原工单。")
    receipt = {
        "kind": confirmation.kind,
        "note": NEGATIVE_NOTES[confirmation.kind],
        "at": now.isoformat(),
        "source_message_id": original.id,
        "report_sha256": digest,
        "confirmed_by_user_id": ticket.user_id,
        "actor": "xiaoc",
        "verification": f"原提交人确认了会话内第 {original.id} 条原始反馈的受理事实。",
        "execution_stop": {"state": "dispatch_blocked", "new_dispatch_blocked": True},
    }
    reply = prepare_disposition(ticket, evidence, receipt, source="assistant_disposition")
    ticket.evidence_json = json_dumps(evidence)
    ticket.status = "rejected"
    ticket.decision_status = "rejected"
    ticket.closed_at = now
    ticket.updated_at = now
    ticket.lock_version += 1
    db.add(
        CustomerServiceAction(
            ticket_id=ticket.id,
            user_id=ticket.user_id,
            action_type="ticket.disposition",
            target_type="ticket",
            target_id=str(ticket.id),
            status="completed",
            request_json=json_dumps(confirmation.model_dump()),
            result_json=json_dumps(receipt),
            idempotency_key=f"xiaoc-ticket-disposition:{original.id}",
        )
    )
    audit(
        db,
        event_type="assistant_ticket_disposed",
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        detail=receipt,
    )
    return reply
