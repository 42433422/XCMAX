from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Header, Query
from fastapi.responses import JSONResponse

from app.fastapi_routes.legacy_helpers import (
    _mp_json_response,
    _mp_jwt_user_id,
    _mp_uid_or_401,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-miniprogram-user"])


@router.post("/api/mp/v1/auth/login")
def mp_v1_auth_login(body: dict = Body(default_factory=dict)):
    from app.application.facades.wechat_facade import (
        WechatMiniProgramError,
        miniprogram_login_data_for_wx_username_binding,
    )

    data = body or {}
    code = (data.get("code") or "").strip()
    if not code:
        return _mp_json_response(400, "code 不能为空", {"error": "missing_code"}, success=False)

    config = {
        "appid": os.environ.get("WECHAT_MINIPROGRAM_APPID", ""),
        "secret": os.environ.get("WECHAT_MINIPROGRAM_SECRET", ""),
    }
    if not config["appid"] or not config["secret"]:
        return _mp_json_response(
            500, "微信小程序配置缺失", {"error": "wechat_api_error"}, success=False
        )
    try:
        payload = miniprogram_login_data_for_wx_username_binding(code)
        return _mp_json_response(200, "登录成功", payload)
    except ValueError:
        return _mp_json_response(400, "code 不能为空", {"error": "missing_code"}, success=False)
    except WechatMiniProgramError as e:
        return _mp_json_response(
            500, str(e), {"error": "wechat_api_error"}, success=False
        )
    except Exception as e:
        logger.exception("mp login: %s", e)
        return _mp_json_response(
            500, f"登录失败：{str(e)}", {"error": "internal_error"}, success=False
        )


@router.post("/api/mp/v1/auth/logout")
def mp_v1_auth_logout(authorization: str | None = Header(default=None)):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    _ = uid
    return _mp_json_response(200, "登出成功", None)


@router.get("/api/mp/v1/auth/session/check")
def mp_auth_session_check(authorization: str | None = Header(default=None)):
    from app.fastapi_routes.legacy_wechat import wechat_session_check

    return wechat_session_check(authorization)


@router.get("/api/mp/v1/user/info")
def mp_user_info(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"error": "missing_token"}, success=False)
    from app.db.models import User
    from app.db.session import get_db

    with get_db() as db:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            return _mp_json_response(404, "用户不存在", {"error": "user_not_found"}, success=False)
        return _mp_json_response(
            200,
            "success",
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name or "微信用户",
                "nickname": user.mp_nickname or "",
                "avatar": user.wx_avatar_url or "",
                "phone": user.mp_phone or "",
                "email": user.email or "",
                "role": user.role,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
        )


@router.put("/api/mp/v1/user/info")
def mp_user_info_put(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import User
    from app.db.session import get_db

    data = body or {}
    with get_db() as db:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            return _mp_json_response(404, "用户不存在", {"error": "user_not_found"}, success=False)
        if "display_name" in data and data["display_name"]:
            user.display_name = data["display_name"]
        if "nickname" in data:
            user.mp_nickname = data["nickname"]
        if "avatar" in data:
            user.wx_avatar_url = data["avatar"]
        db.commit()
        db.refresh(user)
        return _mp_json_response(
            200,
            "更新成功",
            {
                "id": user.id,
                "display_name": user.display_name,
                "nickname": user.mp_nickname,
                "avatar": user.wx_avatar_url or "",
            },
        )


@router.post("/api/mp/v1/user/phone")
def mp_user_phone(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import User
    from app.db.session import get_db

    data = body or {}
    phone = (data.get("phone") or "").strip()
    if not phone:
        return _mp_json_response(400, "手机号不能为空", None, success=False)
    with get_db() as db:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            return _mp_json_response(404, "用户不存在", None, success=False)
        user.mp_phone = phone
        db.commit()
        return _mp_json_response(200, "绑定成功", {"phone": phone})


@router.get("/api/mp/v1/message/list")
def mp_message_list(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    type: str = Query(default=""),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    msg_type = type.strip()
    from app.db.models import MpNotification
    from app.db.session import get_db

    with get_db() as db:
        query = db.query(MpNotification).filter(MpNotification.user_id == uid)
        if msg_type and msg_type != "all":
            query = query.filter(MpNotification.type == msg_type)
        query = query.order_by(MpNotification.created_at.desc())
        total = query.count()
        messages = query.offset((page - 1) * page_size).limit(page_size).all()
        result = []
        for msg in messages:
            result.append(
                {
                    "id": msg.id,
                    "title": msg.title,
                    "content": (msg.content or "")[:200],
                    "type": msg.type,
                    "is_read": msg.is_read,
                    "related_type": msg.related_type,
                    "related_id": msg.related_id,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
            )
        from app.fastapi_routes.legacy_helpers import _mp_paginate

        return _mp_paginate(result, total, page, page_size)


@router.get("/api/mp/v1/message/unread-count")
def mp_message_unread_count(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    from app.db.models import MpNotification
    from app.db.session import get_db

    with get_db() as db:
        count = (
            db.query(MpNotification)
            .filter(
                MpNotification.user_id == uid,
                MpNotification.is_read == False,
            )
            .count()
        )
        return _mp_json_response(200, "success", {"count": count})


@router.put("/api/mp/v1/message/read/{msg_id}")
def mp_message_read(msg_id: int, authorization: str | None = Header(default=None)):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpNotification
    from app.db.session import get_db

    with get_db() as db:
        msg = (
            db.query(MpNotification)
            .filter(MpNotification.id == msg_id, MpNotification.user_id == uid)
            .first()
        )
        if not msg:
            return _mp_json_response(404, "消息不存在", None, success=False)
        msg.is_read = True
        db.commit()
        return _mp_json_response(200, "已标记为已读", None)


@router.put("/api/mp/v1/message/read-all")
def mp_message_read_all(authorization: str | None = Header(default=None)):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpNotification
    from app.db.session import get_db

    with get_db() as db:
        db.query(MpNotification).filter(
            MpNotification.user_id == uid, MpNotification.is_read == False
        ).update({"is_read": True})
        db.commit()
        return _mp_json_response(200, "全部已读", None)


@router.get("/api/mp/v1/feedback/list")
def mp_feedback_list(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    from app.db.models import MpFeedback
    from app.db.session import get_db

    with get_db() as db:
        query = (
            db.query(MpFeedback)
            .filter(MpFeedback.user_id == uid)
            .order_by(MpFeedback.created_at.desc())
        )
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        result = []
        for fb in items:
            result.append(
                {
                    "id": fb.id,
                    "type": fb.type,
                    "content": fb.content[:200],
                    "status": fb.status,
                    "has_reply": bool(fb.reply),
                    "replied_at": fb.replied_at.isoformat() if fb.replied_at else None,
                    "created_at": fb.created_at.isoformat() if fb.created_at else None,
                }
            )
        from app.fastapi_routes.legacy_helpers import _mp_paginate

        return _mp_paginate(result, total, page, page_size)


@router.get("/api/mp/v1/feedback/detail/{feedback_id}")
def mp_feedback_detail(feedback_id: int, authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    import json as _json

    from app.db.models import MpFeedback
    from app.db.session import get_db

    with get_db() as db:
        fb = (
            db.query(MpFeedback)
            .filter(MpFeedback.id == feedback_id, MpFeedback.user_id == uid)
            .first()
        )
        if not fb:
            return _mp_json_response(404, "反馈不存在", success=False)
        images = []
        if fb.images:
            try:
                images = _json.loads(fb.images)
            except Exception:
                images = []
        return _mp_json_response(
            200,
            "success",
            {
                "id": fb.id,
                "type": fb.type,
                "content": fb.content,
                "images": images,
                "status": fb.status,
                "reply": fb.reply or "",
                "replied_at": fb.replied_at.isoformat() if fb.replied_at else None,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
            },
        )


@router.post("/api/mp/v1/feedback/submit")
def mp_feedback_submit(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    from app.db.models import MpFeedback
    from app.db.session import get_db

    data = body or {}
    fb_type = (data.get("type") or "").strip()
    content = (data.get("content") or "").strip()
    images = data.get("images", [])
    valid_types = ["bug", "suggestion", "complaint", "other"]
    if fb_type not in valid_types:
        return _mp_json_response(400, "反馈类型无效", None, success=False)
    if not content:
        return _mp_json_response(400, "反馈内容不能为空", None, success=False)
    if len(content) > 1000:
        return _mp_json_response(400, "反馈内容不能超过1000字", None, success=False)
    with get_db() as db:
        feedback = MpFeedback(
            user_id=uid,
            type=fb_type,
            content=content,
            images=json.dumps(images) if images else None,
            status="pending",
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)
        return _mp_json_response(200, "提交成功，感谢您的反馈！", {"feedback_id": feedback.id})


@router.get("/api/mp/v1/ai/history")
def mp_ai_history(
    authorization: str | None = Header(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    from app.db.models import AIConversation, AIConversationSession
    from app.db.session import get_db

    try:
        with get_db() as db:
            sessions = (
                db.query(AIConversationSession)
                .filter(AIConversationSession.user_id == uid)
                .order_by(AIConversationSession.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            result = []
            for session in sessions:
                last_msg = (
                    db.query(AIConversation)
                    .filter(AIConversation.session_id == session.id)
                    .order_by(AIConversation.created_at.desc())
                    .first()
                )
                result.append(
                    {
                        "session_id": session.id,
                        "last_message": last_msg.content[:100] if last_msg else "",
                        "updated_at": (
                            session.updated_at.isoformat() if session.updated_at else None
                        ),
                    }
                )
            return _mp_json_response(200, "success", result)
    except Exception as e:
        logger.error("mp ai history: %s", e)
        return _mp_json_response(500, "获取历史失败", success=False)


@router.get("/api/mp/v1/ai/intents")
def mp_ai_intents():
    intents = [
        {"key": "price_inquiry", "label": "询价", "example": "这个产品多少钱？"},
        {"key": "product_search", "label": "找产品", "example": "有没有白色的底漆？"},
        {"key": "order_status", "label": "查订单", "example": "我的订单到哪了？"},
        {"key": "after_sales", "label": "售后", "example": "产品质量有问题怎么办？"},
        {"key": "other", "label": "其他问题", "example": "我想咨询其他问题"},
    ]
    return _mp_json_response(200, "success", intents)


@router.post("/api/mp/v1/ai/chat")
def mp_v1_ai_chat(
    authorization: str | None = Header(default=None), body: dict = Body(default_factory=dict)
):
    uid, err = _mp_uid_or_401(authorization)
    if err:
        return err
    data = body or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id")
    if not message:
        return _mp_json_response(400, "消息内容不能为空", None, success=False)
    try:
        from app.application.facades.ai_conversation_facade import AIConversationService

        service = AIConversationService()
        response_text = service.chat(
            message=message,
            user_id=uid,
            session_id=session_id,
            source="miniprogram",
        )
        return _mp_json_response(200, "ok", {"reply": response_text, "message": message})
    except Exception as e:
        logger.exception("mp ai chat: %s", e)
        return _mp_json_response(500, f"AI 服务暂时不可用: {str(e)}", None, success=False)
