"""IM V0 REST + WebSocket。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.application.im_app_service import ImApplicationService, ensure_im_tables
from app.config import Config
from app.db import SessionLocal, engine
from app.infrastructure.auth.dependencies import (
    CurrentUser,
    require_identified_user,
)
from app.infrastructure.im.ws_hub import im_ws_hub
from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["im-v0"])

_schema_ready = False


def _ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    ensure_im_tables(engine)
    _schema_ready = True


def _uid(user: CurrentUser) -> int:
    if user.user_id is None:
        raise ValueError("user_id required")
    return int(user.user_id)


def _resolve_ws_user_id(ws: WebSocket) -> int | None:
    cookie_name = getattr(Config, "SESSION_COOKIE_NAME", "session_id")
    sid = ws.cookies.get(cookie_name) or ws.query_params.get("session_id")
    if not sid:
        return None
    from app.services import get_session_service

    user = get_session_service().validate_session(str(sid).strip())
    if user is None:
        return None
    return int(user.id)


async def _notify_offline_im_members(member_ids: list[int], sender_id: int, body: str) -> None:
    online = set(im_ws_hub.connected_user_ids())
    offline = [int(mid) for mid in member_ids if int(mid) != sender_id and int(mid) not in online]
    if not offline:
        return
    try:
        from app.services.mobile_push import notify_user

        preview = (body or "").strip()[:120] or "新消息"
        for uid in offline:
            notify_user(
                uid,
                title="新消息",
                body=preview,
                data={"channel": "xcagi_im", "type": "im_message"},
            )
    except OPERATIONAL_ERRORS:
        logger.exception("im offline push failed")


@router.get("/api/im/conversations")
def im_list_conversations(user: CurrentUser = Depends(require_identified_user)):
    _ensure_schema()
    uid = _uid(user)
    db = SessionLocal()
    try:
        items = ImApplicationService(db).list_conversations(uid)
        return {"success": True, "user_id": uid, "conversations": items}
    except OPERATIONAL_ERRORS as exc:
        logger.exception("im_list_conversations")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/contacts")
def im_list_contacts(
    q: str | None = Query(default=None),
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    db = SessionLocal()
    try:
        contacts = ImApplicationService(db).list_contacts(uid)
        keyword = (q or "").strip().lower()
        if keyword:
            contacts = [
                c
                for c in contacts
                if keyword in str(c.get("display_name", "")).lower()
                or keyword in str(c.get("username", "")).lower()
            ]
        return {"success": True, "contacts": contacts}
    except OPERATIONAL_ERRORS as exc:
        logger.exception("im_list_contacts")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/unread-total")
def im_unread_total(user: CurrentUser = Depends(require_identified_user)):
    _ensure_schema()
    uid = _uid(user)
    db = SessionLocal()
    try:
        items = ImApplicationService(db).list_conversations(uid)
        total = sum(int(c.get("unread_count") or 0) for c in items)
        return {"success": True, "unread_total": total}
    except OPERATIONAL_ERRORS as exc:
        logger.exception("im_unread_total")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/direct")
def im_create_direct(
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    peer = int(body.get("peer_user_id") or 0)
    if peer <= 0:
        return JSONResponse({"success": False, "message": "peer_user_id 无效"}, status_code=400)
    db = SessionLocal()
    try:
        conv = ImApplicationService(db).get_or_create_direct(uid, peer)
        return {"success": True, "conversation": conv}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except OPERATIONAL_ERRORS as exc:
        logger.exception("im_create_direct")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/conversations/{conversation_id}/messages")
def im_list_messages(
    conversation_id: int,
    user: CurrentUser = Depends(require_identified_user),
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None),
):
    _ensure_schema()
    uid = _uid(user)
    db = SessionLocal()
    try:
        messages = ImApplicationService(db).list_messages(
            conversation_id, uid, limit=limit, before_id=before_id
        )
        return {"success": True, "messages": messages}
    except PermissionError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
    except OPERATIONAL_ERRORS as exc:
        logger.exception("im_list_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/{conversation_id}/messages")
async def im_send_message(
    conversation_id: int,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    db = SessionLocal()
    try:
        result = ImApplicationService(db).send_message(
            conversation_id, uid, str(body.get("body") or "")
        )
        payload = {
            "type": "message",
            "conversation_id": conversation_id,
            "message": result["message"],
        }
        member_ids = [int(mid) for mid in (result.get("member_user_ids") or [])]
        for member_id in member_ids:
            if member_id != uid:
                await im_ws_hub.send_to_user(member_id, payload)
        await _notify_offline_im_members(member_ids, uid, str(body.get("body") or ""))
        return {"success": True, **result}
    except PermissionError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except OPERATIONAL_ERRORS as exc:
        logger.exception("im_send_message")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/{conversation_id}/read")
def im_mark_read(
    conversation_id: int,
    body: dict = Body(default_factory=dict),
    user: CurrentUser = Depends(require_identified_user),
):
    _ensure_schema()
    uid = _uid(user)
    last_id = int(body.get("last_message_id") or 0)
    db = SessionLocal()
    try:
        ImApplicationService(db).mark_read(conversation_id, uid, last_id)
        return {"success": True}
    except PermissionError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
    except OPERATIONAL_ERRORS as exc:
        logger.exception("im_mark_read")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.websocket("/ws/im")
async def im_websocket(ws: WebSocket):
    _ensure_schema()
    await ws.accept()
    uid = _resolve_ws_user_id(ws)
    if uid is None:
        await ws.close(code=4401, reason="unauthorized")
        return
    await im_ws_hub.connect(uid, ws)
    try:
        while True:
            raw = await ws.receive_text()
            if raw.strip().lower() in {"ping", '{"type":"ping"}'}:
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    finally:
        await im_ws_hub.disconnect(uid, ws)
