"""Bounded message and screenshot reads for customer-service conversations."""

from fastapi import HTTPException, Response
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Query, Session

from modstore_server import customer_service_customer_view as customer_view
from modstore_server.customer_service_tools import json_loads
from modstore_server.models_cs import CustomerServiceMessage as Message
from modstore_server.models_cs import CustomerServiceTicket

TRANSCRIPT_PAGE_SIZE = 24
MAX_MESSAGE_METADATA_LENGTH = 64_000
MAX_TICKET_SCREENSHOT_STORAGE = 24_000_000


def conversation_messages(db: Session, session_id: int, user_id: int) -> Query:
    return db.query(Message).filter_by(session_id=session_id, user_id=user_id)


def _stored_screenshot():
    return (Message.role == "user") & or_(
        Message.payload_json.contains('"image_data_url":"data:image/', autoescape=True),
        Message.payload_json.contains('"image_data_url": "data:image/', autoescape=True),
    )


def read_session_context(context_json: str | None) -> dict:
    context = json_loads(context_json, {})
    if not isinstance(context, dict):
        return {}
    context.pop("image_data_url", None)
    return context


def user_message_payload(
    db: Session,
    session_id: int,
    user_id: int,
    ticket: CustomerServiceTicket | None,
    context: dict,
    image: str,
) -> dict:
    if not image:
        return {"context": context}
    db.flush()
    _enforce_screenshot_quota(
        db, session_id, user_id, int(ticket.id) if ticket is not None else None, len(image)
    )
    return {"context": {**context, "has_image": True}, "image_data_url": image, "has_image": True}


def _enforce_screenshot_quota(
    db: Session, session_id: int, user_id: int, ticket_id: int | None, image_length: int
) -> None:
    # The caller serializes writes to this session before checking persisted messages.
    total = (
        conversation_messages(db, session_id, user_id)
        .filter(_stored_screenshot())
        .filter(or_(Message.ticket_id == ticket_id, Message.ticket_id.is_(None)))
        .with_entities(func.coalesce(func.sum(func.length(Message.payload_json)), 0))
        .scalar()
    )
    if total + image_length > MAX_TICKET_SCREENSHOT_STORAGE:
        raise HTTPException(413, "此工单的截图已达容量上限，可继续补充文字")


def read_message_page(
    query: Query,
    before_id: int | None,
    *,
    customer_visible: bool,
    inline_small_images: bool = False,
) -> dict:
    if before_id is not None:
        query = query.filter(Message.id < before_id)
    # Project away large blobs in SQL, before ORM materialization or JSON serialization.
    rows = (
        query.with_entities(
            Message.id,
            Message.ticket_id,
            Message.role,
            Message.content,
            case(
                (
                    func.length(Message.payload_json) <= MAX_MESSAGE_METADATA_LENGTH,
                    Message.payload_json,
                )
            ),
            Message.created_at,
            _stored_screenshot(),
        )
        .order_by(Message.id.desc())
        .limit(TRANSCRIPT_PAGE_SIZE + 1)
        .all()
    )
    page = rows[:TRANSCRIPT_PAGE_SIZE]
    messages = []
    for (
        message_id,
        ticket_id,
        role,
        content,
        payload_json,
        created_at,
        stored_screenshot,
    ) in reversed(page):
        payload = json_loads(payload_json, {})
        payload = payload if isinstance(payload, dict) else {}
        image = payload.pop("image_data_url", None)
        message = {
            "id": message_id,
            "ticket_id": ticket_id,
            "role": role,
            "content": content,
            "payload": payload,
            "created_at": created_at.isoformat() if created_at else "",
        }
        if customer_visible:
            message = customer_view.customer_message(message)
        # Small historical session attachments remain inline for legacy clients; ticket pages use a reference.
        if role == "user" and (
            (payload_json is None and stored_screenshot) or customer_view.decode_screenshot(image)
        ):
            message["payload"]["has_screenshot"] = True
            if inline_small_images and image:
                message["payload"]["image_data_url"] = image
        messages.append(message)
    return {
        "messages": messages,
        "next_before_id": page[-1].id if len(rows) > TRANSCRIPT_PAGE_SIZE else None,
    }


def read_message_screenshot(query: Query, message_id: int) -> Response:
    payload = (
        query.filter(
            Message.id == message_id,
            Message.role == "user",
            func.length(Message.payload_json)
            <= customer_view.MAX_SCREENSHOT_DATA_LENGTH + MAX_MESSAGE_METADATA_LENGTH,
        )
        .with_entities(Message.payload_json)
        .scalar()
    )
    parsed = json_loads(payload, {})
    image = customer_view.decode_screenshot(
        parsed.get("image_data_url") if isinstance(parsed, dict) else None
    )
    if image is None:
        raise HTTPException(404, "截图不存在")
    media_type, content = image
    return Response(
        content,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )
