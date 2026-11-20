# mypy: disable-error-code="arg-type"
"""Persist replies in the original chat before a ticket has been submitted."""

from __future__ import annotations

import hashlib
from typing import Any, cast

from sqlalchemy.orm import Session

from modstore_server.customer_service_tools import audit, json_dumps
from modstore_server.customer_ticket_disposition import has_linked_support_material
from modstore_server.customer_ticket_intake_review import IntakeReview, cached_intake_review
from modstore_server.models import User
from modstore_server.models_cs import CustomerServiceMessage


def read_chat_assessment(
    db: Session, session_id: int, owner_id: int, report: str
) -> IntakeReview | None:
    replies = (
        db.query(CustomerServiceMessage)
        .filter_by(session_id=session_id, user_id=owner_id, role="assistant")
        .order_by(CustomerServiceMessage.id.desc())
        .limit(8)
        .all()
    )
    return cached_intake_review(report, (cast(str | None, reply.payload_json) for reply in replies))


def record_chat_only_reply(
    db: Session,
    *,
    original: CustomerServiceMessage,
    user: User,
    session: dict[str, Any],
    default_reply: str,
    intent: str,
    classified: dict[str, Any],
    extracted: dict[str, Any],
    reviewed_report: str | None,
    intake_review: IntakeReview | None,
    may_offer_confirmation: bool,
) -> dict[str, Any]:
    reply = default_reply
    payload: dict[str, Any] = {
        "ticket": None,
        "decision": None,
        "actions": [],
        "cards": [],
        "intent": classified,
        "intake_assessment": {},
    }
    if intake_review is not None and reviewed_report:
        payload["intake_assessment"] = {
            "report_sha256": hashlib.sha256(reviewed_report.encode()).hexdigest(),
            "review": intake_review.model_dump(),
        }
        if (
            may_offer_confirmation
            and intake_review.disposition in ("invalid", "out_of_scope")
            and reviewed_report == original.content
            and not has_linked_support_material(extracted)
        ):
            payload["intake_confirmation"] = {
                "source_message_id": original.id,
                "kind": intake_review.disposition,
            }
    if intake_review and intake_review.disposition != "actionable":
        review_note = {
            "invalid": "收到你说明的演练情景。",
            "out_of_scope": "这项问题超出平台客服处理范围。",
            "needs_review": "目前无法确认反馈的处理范围。",
        }[intake_review.disposition]
        reply = f"我是小C。{review_note}如需留存原文供管理员核实，可以点击「提交工单」。"
    db.add(
        CustomerServiceMessage(
            session_id=original.session_id,
            ticket_id=original.ticket_id,
            user_id=original.user_id,
            role="assistant",
            content=reply,
            payload_json=json_dumps(payload),
        )
    )
    audit(
        db,
        event_type="chat_only_reply",
        session_id=original.session_id,
        actor=user,
        detail={"intent": intent, "classified": classified, "extracted": extracted},
    )
    return {
        "ok": True,
        "session": session,
        "message": {"role": "assistant", "content": reply, "payload": payload},
        **{key: payload[key] for key in ("ticket", "decision", "actions", "cards", "intent")},
    }
