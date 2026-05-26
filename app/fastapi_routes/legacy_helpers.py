from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 纯工具模块；历史路由已迁出，保留空 router 供 legacy_gaps_batch1 聚合 include。
router = APIRouter()


def _secret_key() -> str:
    return os.environ.get("SECRET_KEY", "")


def _mp_jwt_user_id(authorization: str | None) -> int | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    try:
        secret_key = _secret_key()
        parts = token.split(".")
        if len(parts) != 3:
            return None

        def b64url_decode(data: str) -> bytes:
            padding = "=" * (4 - len(data) % 4)
            return base64.urlsafe_b64decode(data + padding)

        payload = json.loads(b64url_decode(parts[1]).decode("utf-8"))
        signature = b64url_decode(parts[2])
        message = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        uid = payload.get("user_id")
        return int(uid) if uid is not None else None
    except Exception:
        return None


def _mp_json_response(
    code: int, message: str, data: Any = None, *, success: bool = True
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "success": success}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=code)


def _mp_wechat_json_response(
    code: int, message: str, data: Any = None, *, success: bool = True
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "success": success}
    if data is not None:
        body["data"] = data
    return JSONResponse(body, status_code=code)


def _mp_paginate(items: list, total: int, page: int, page_size: int) -> JSONResponse:
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    payload = {
        "items": items,
        "pagination": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }
    return _mp_json_response(200, "success", payload)


def _session_id_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    cookie_name = os.environ.get("SESSION_COOKIE_NAME", "session_id")
    return (request.cookies.get(cookie_name) or "").strip()


def _user_from_mobile_bearer(request: Request):
    """移动端 JWT（aud=xcagi-mobile）解析为 User，失败返回 None。"""
    from app.db.models import User
    from app.db.session import get_db
    from app.security.mobile_jwt import user_id_from_mobile_bearer

    auth = request.headers.get("Authorization") or ""
    uid = user_id_from_mobile_bearer(auth)
    if uid is None:
        return None
    with get_db() as db:
        user = db.query(User).filter(User.id == uid).first()
        if user and user.is_active:
            return user
    return None


def _require_login_user(request: Request):
    mobile_user = _user_from_mobile_bearer(request)
    if mobile_user is not None:
        return mobile_user, None

    from app.application.facades.session_facade import get_session_service

    sid = _session_id_from_request(request)
    if not sid:
        return None, JSONResponse(
            {"success": False, "message": {"code": "UNAUTHORIZED", "message": "请先登录"}},
            status_code=401,
        )
    user = get_session_service().validate_session(sid)
    if not user:
        return None, JSONResponse(
            {
                "success": False,
                "message": {"code": "SESSION_EXPIRED", "message": "会话已过期，请重新登录"},
            },
            status_code=401,
        )
    if not user.is_active:
        return None, JSONResponse(
            {"success": False, "message": {"code": "ACCOUNT_DISABLED", "message": "账户已被禁用"}},
            status_code=403,
        )
    return user, None


def _require_permission(request: Request, permission_code: str):
    user, err = _require_login_user(request)
    if err:
        return None, err
    from app.application.facades.session_facade import get_auth_service

    auth_service = get_auth_service()
    if not auth_service.has_permission(user, permission_code):
        return None, JSONResponse(
            {"success": False, "message": {"code": "FORBIDDEN", "message": "权限不足"}},
            status_code=403,
        )
    return user, None


def _session_to_dict(session: object) -> dict:
    if isinstance(session, dict):
        return {
            "session_id": session.get("session_id"),
            "user_id": session.get("user_id"),
            "title": session.get("title") or "新会话",
            "summary": session.get("summary") or "",
            "message_count": session.get("message_count", 0),
            "last_message_at": session.get("last_message_at"),
            "created_at": session.get("created_at"),
        }
    if isinstance(session, tuple):
        return {
            "session_id": session[1] if len(session) > 1 else None,
            "user_id": session[2] if len(session) > 2 else None,
            "title": (session[3] if len(session) > 3 else None) or "新会话",
            "summary": (session[4] if len(session) > 4 else None) or "",
            "message_count": session[5] if len(session) > 5 else 0,
            "last_message_at": session[6] if len(session) > 6 else None,
            "created_at": session[7] if len(session) > 7 else None,
        }
    return {
        "session_id": getattr(session, "session_id", None),
        "user_id": getattr(session, "user_id", None),
        "title": getattr(session, "title", None) or "新会话",
        "summary": getattr(session, "summary", "") or "",
        "message_count": getattr(session, "message_count", 0),
        "last_message_at": getattr(session, "last_message_at", None),
        "created_at": getattr(session, "created_at", None),
    }


def _message_to_dict(message: object) -> dict:
    if isinstance(message, dict):
        return {
            "id": message.get("id"),
            "session_id": message.get("session_id"),
            "user_id": message.get("user_id"),
            "role": message.get("role"),
            "content": message.get("content"),
            "intent": message.get("intent") or "",
            "metadata": message.get("metadata") or message.get("conversation_metadata") or "",
            "created_at": message.get("created_at"),
        }
    if isinstance(message, tuple):
        return {
            "id": message[0] if len(message) > 0 else None,
            "session_id": message[1] if len(message) > 1 else None,
            "user_id": message[2] if len(message) > 2 else None,
            "role": message[3] if len(message) > 3 else None,
            "content": message[4] if len(message) > 4 else None,
            "intent": (message[5] if len(message) > 5 else "") or "",
            "metadata": (message[6] if len(message) > 6 else "") or "",
            "created_at": message[7] if len(message) > 7 else None,
        }
    return {
        "id": getattr(message, "id", None),
        "session_id": getattr(message, "session_id", None),
        "user_id": getattr(message, "user_id", None),
        "role": getattr(message, "role", None),
        "content": getattr(message, "content", None),
        "intent": getattr(message, "intent", "") or "",
        "metadata": getattr(message, "conversation_metadata", "") or "",
        "created_at": getattr(message, "created_at", None),
    }


def _mp_uid_or_401(authorization: str | None):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return None, _mp_json_response(401, "未授权", {"message": "missing_token"}, success=False)
    return uid, None


def _mp_generate_order_no() -> str:
    import random
    import string
    from datetime import datetime

    prefix = datetime.now().strftime("%Y%m%d%H%M%S")
    suffix = "".join(random.choices(string.digits, k=6))
    return f"MP{prefix}{suffix}"


def _dispatch_tool_for_approval(
    *, tool_id: str, action: str, params: dict | None = None
) -> dict[str, Any]:
    from app.routes.tools import execute_registered_workflow_tool

    return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
