from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.legacy_helpers import (
    _mp_jwt_user_id,
    _mp_json_response,
    _mp_wechat_json_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["legacy-wechat"])


def _secret_key() -> str:
    return os.environ.get("SECRET_KEY", "")


@router.get("/api/wechat/tasks")
def wechat_tasks(
    status: str = Query(default="pending"),
    contact_id: int | None = Query(default=None),
    limit: int = Query(default=20),
):
    try:
        from app.application import get_wechat_task_app_service

        service = get_wechat_task_app_service()
        tasks = service.get_tasks(contact_id=contact_id, status=status, limit=limit)
        return {"success": True, "data": tasks, "total": len(tasks)}
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


def _wechat_message_timestamp_seconds(msg: dict) -> float:
    import datetime as _dt

    for key in ("timestamp", "msg_timestamp", "time", "created_at", "msg_time"):
        raw = msg.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            v = float(raw)
            return v / 1000.0 if v > 1e12 else v
        text = str(raw).strip()
        if not text:
            continue
        try:
            iso = text.replace("Z", "+00:00")
            return _dt.datetime.fromisoformat(iso).timestamp()
        except Exception:
            continue
    return 0.0


def _wechat_message_text(msg: dict) -> str:
    for key in ("content", "message", "text", "raw_text", "body"):
        val = msg.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


@router.get("/api/wechat/starred-messages")
def wechat_starred_messages(limit: int = Query(default=10, ge=1, le=50)):
    """星标联系人最近一条上下文消息（来自 wechat_contact_context），供企业客服摘要。"""
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        contacts = service.get_contacts(starred_only=True, limit=80)
        items: list[dict] = []
        for c in contacts:
            cid = c.get("id")
            if cid is None:
                continue
            messages = service.get_contact_context(int(cid))
            if not messages:
                continue
            last = messages[-1]
            if not isinstance(last, dict):
                continue
            text = _wechat_message_text(last)
            ts = _wechat_message_timestamp_seconds(last)
            display_name = (c.get("contact_name") or "").strip() or "联系人"
            items.append(
                {
                    "id": f"{cid}-{ts}",
                    "contact_id": cid,
                    "contact_name": display_name,
                    "nickname": (c.get("remark") or "").strip() or display_name,
                    "content": text,
                    "message": text,
                    "timestamp": ts,
                    "created_at": ts,
                }
            )
        items.sort(key=lambda row: float(row.get("timestamp") or 0), reverse=True)
        page = items[:limit]
        return {"success": True, "data": page, "total": len(items)}
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.get("/api/wechat/contacts")
def wechat_contacts_list_api(
    keyword: str | None = Query(default=None),
    type: str = Query(default="all"),
    starred: str = Query(default="false"),
    limit: int = Query(default=100),
):
    try:
        from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler

        mod_out = try_invoke_erp_domain_handler(
            "wechat",
            "contacts_list",
            keyword=keyword,
            type=type,
            starred=starred,
            limit=limit,
        )
        if mod_out is not None:
            return mod_out
    except Exception:
        import logging

        logging.getLogger(__name__).debug(
            "erp domain wechat.contacts_list dispatch skipped", exc_info=True
        )
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        contacts = service.get_contacts(
            keyword=keyword,
            contact_type=type if type != "all" else None,
            starred_only=starred.lower() == "true",
            limit=limit,
        )
        return {"success": True, "data": contacts, "total": len(contacts)}
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.get("/api/wechat/contacts/{contact_id}")
def wechat_contact_get_api(contact_id: int):
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        contact = service.get_contact_by_id(contact_id)
        if contact:
            return {"success": True, "data": contact}
        return JSONResponse({"success": False, "message": "联系人不存在"}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.delete("/api/wechat/contacts/{contact_id}")
def wechat_contact_delete_api(contact_id: int):
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        result = service.delete_contact(contact_id)
        return JSONResponse(result, status_code=200 if result.get("success") else 400)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"删除失败：{str(e)}"}, status_code=500)


@router.get("/api/wechat/contacts/{contact_id}/context")
def wechat_contact_context_api(contact_id: int):
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        messages = service.get_contact_context(contact_id)
        return {"success": True, "messages": messages, "count": len(messages)}
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.post("/api/wechat/contacts")
def wechat_contacts_post(body: dict = Body(default_factory=dict)):
    from app.application import get_wechat_contact_app_service

    data = body or {}
    contact_name = (data.get("contact_name") or "").strip()
    if not contact_name:
        return JSONResponse({"success": False, "message": "联系人名称不能为空"}, status_code=400)
    service = get_wechat_contact_app_service()
    result = service.add_contact(
        contact_name=contact_name,
        remark=(data.get("remark") or "").strip(),
        wechat_id=(data.get("wechat_id") or "").strip(),
        contact_type=data.get("contact_type", "contact"),
        is_starred=data.get("is_starred", True),
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.put("/api/wechat/contacts/{contact_id}")
def wechat_contacts_put(contact_id: int, body: dict = Body(default_factory=dict)):
    from app.application import get_wechat_contact_app_service

    data = body or {}
    service = get_wechat_contact_app_service()
    result = service.update_contact(
        contact_id=contact_id,
        contact_name=(data.get("contact_name") or "").strip() or None,
        remark=(data.get("remark") or "").strip() or None,
        wechat_id=(data.get("wechat_id") or "").strip() or None,
        contact_type=data.get("contact_type"),
        is_starred=data.get("is_starred"),
    )
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.post("/api/wechat/contacts/{contact_id}/star")
def wechat_contacts_star(contact_id: int, body: dict = Body(default_factory=dict)):
    from app.application import get_wechat_contact_app_service

    data = body or {}
    starred = data.get("starred", True)
    service = get_wechat_contact_app_service()
    star_fn = getattr(service, "star_contact", None)
    if callable(star_fn):
        result = star_fn(contact_id, starred)
    else:
        result = service.update_contact(contact_id=contact_id, is_starred=starred)
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.post("/api/wechat/contacts/unstar-all")
def wechat_contacts_unstar_all():
    from app.application import get_wechat_contact_app_service

    return get_wechat_contact_app_service().unstar_all()


@router.get("/api/wechat/status")
def wechat_status():
    try:
        from app.utils.path_utils import get_resource_path

        wechat_cv_path = get_resource_path("wechat_cv")
        if os.path.isdir(wechat_cv_path) and wechat_cv_path not in sys.path:
            sys.path.insert(0, wechat_cv_path)
        from wechat_cv_send import _find_wechat_handle

        hwnd = _find_wechat_handle()
        is_logined = hwnd is not None
        return {
            "success": True,
            "logined": is_logined,
            "message": "微信已登录" if is_logined else "微信未登录",
        }
    except Exception as e:
        return {"success": False, "logined": False, "message": f"检测失败：{str(e)}"}


@router.get("/api/wechat/test")
def wechat_test():
    return {"success": True, "message": "微信服务运行正常"}


@router.get("/api/wechat/session/check")
def wechat_session_check(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        return _mp_json_response(401, "未授权", {"error": "缺少 token"}, success=False)
    token = authorization[7:].strip()
    try:
        secret_key = _secret_key()
        parts = token.split(".")
        if len(parts) != 3:
            return _mp_json_response(
                401, "token 无效或已过期", {"error": "invalid_token"}, success=False
            )

        def b64url_decode(data: str) -> bytes:
            padding = "=" * (4 - len(data) % 4)
            return base64.urlsafe_b64decode(data + padding)

        payload = json.loads(b64url_decode(parts[1]).decode("utf-8"))
        signature = b64url_decode(parts[2])
        message = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return _mp_json_response(
                401, "token 无效或已过期", {"error": "invalid_token"}, success=False
            )
        if int(payload.get("exp", 0)) < int(time.time()):
            return _mp_json_response(401, "会话已过期", {"error": "session_expired"}, success=False)
        return _mp_json_response(
            200,
            "会话有效",
            {
                "user_id": payload.get("user_id"),
                "openid": payload.get("openid"),
                "expires_at": payload.get("exp"),
            },
        )
    except Exception as e:
        logger.error("wechat session check: %s", e)
        return _mp_json_response(
            500, f"检查失败：{str(e)}", {"error": "internal_error"}, success=False
        )


@router.get("/api/wechat/user/info")
def wechat_user_info_miniprogram(authorization: str | None = Header(default=None)):
    uid = _mp_jwt_user_id(authorization)
    if uid is None:
        return _mp_json_response(401, "未授权", {"error": "缺少 token"}, success=False)
    try:
        from app.db.models import User
        from app.db.session import get_db

        with get_db() as db:
            user = db.query(User).filter(User.id == uid).first()
            if not user:
                return _mp_json_response(
                    404, "用户不存在", {"error": "user_not_found"}, success=False
                )
            return _mp_json_response(
                200,
                "获取成功",
                {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "email": user.email,
                    "role": user.role,
                    "avatar": "",
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                },
            )
    except Exception as e:
        logger.error("wechat user info: %s", e)
        return _mp_json_response(
            500, f"获取失败：{str(e)}", {"error": "internal_error"}, success=False
        )


@router.put("/api/wechat/user/info")
def wechat_user_info_put(request: Request, body: dict = Body(default_factory=dict)):
    from app.decorators.mp_auth import verify_jwt_token

    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return _mp_wechat_json_response(401, "未授权", {"error": "缺少 token"}, success=False)
    payload = verify_jwt_token(auth[7:].strip())
    if not payload:
        return _mp_wechat_json_response(
            401, "token 无效或已过期", {"error": "invalid_token"}, success=False
        )
    uid = payload.get("user_id")
    from app.db.models import User
    from app.db.session import get_db

    data = body or {}
    with get_db() as db:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            return _mp_wechat_json_response(
                404, "用户不存在", {"error": "user_not_found"}, success=False
            )
        if "display_name" in data:
            user.display_name = data["display_name"]
        db.commit()
        db.refresh(user)
        return _mp_wechat_json_response(
            200,
            "更新成功",
            {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "role": user.role,
                "avatar": "",
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
        )


@router.post("/api/wechat/task/{task_id}/confirm")
def wechat_task_confirm(task_id: int):
    from app.application import get_wechat_task_app_service

    result = get_wechat_task_app_service().confirm_task(task_id)
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.post("/api/wechat/task/{task_id}/ignore")
def wechat_task_ignore(task_id: int):
    from app.application import get_wechat_task_app_service

    result = get_wechat_task_app_service().ignore_task(task_id)
    return JSONResponse(result, status_code=200 if result.get("success") else 400)


@router.post("/api/wechat/scan")
def wechat_scan(body: dict = Body(default_factory=dict)):
    data = body or {}
    try:
        from app.tasks.wechat_tasks import scan_wechat_messages

        task = scan_wechat_messages.delay(
            contact_id=data.get("contact_id"), limit=data.get("limit", 20)
        )
        return JSONResponse(
            {"success": True, "message": "扫描任务已触发", "task_id": task.id, "count": 0},
            status_code=202,
        )
    except Exception as e:
        return JSONResponse({"success": False, "message": f"扫描失败：{str(e)}"}, status_code=500)


@router.post("/api/wechat/login")
def wechat_miniprogram_style_login(body: dict = Body(default_factory=dict)):
    from app.application.facades.wechat_facade import (
        WechatMiniProgramError,
        miniprogram_login_data_for_wx_username_binding,
    )

    data = body or {}
    code = (data.get("code") or "").strip()
    if not code:
        return _mp_wechat_json_response(
            400, "code 不能为空", {"error": "missing_code"}, success=False
        )
    try:
        payload = miniprogram_login_data_for_wx_username_binding(code)
        return _mp_wechat_json_response(200, "登录成功", payload)
    except WechatMiniProgramError as e:
        logger.error("wechat login: %s", e)
        return _mp_wechat_json_response(500, str(e), {"error": "wechat_api_error"}, success=False)
    except Exception as e:
        logger.exception("wechat login: %s", e)
        return _mp_wechat_json_response(
            500, f"登录失败：{str(e)}", {"error": "internal_error"}, success=False
        )


@router.get("/api/wechat_contacts/{contact_id}")
def wechat_contacts_get_by_id(contact_id: int):
    try:
        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        contact = service.get_contact_by_id(contact_id)
        if contact:
            return {"success": True, "data": contact}
        return JSONResponse({"success": False, "message": "联系人不存在"}, status_code=404)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"查询失败：{str(e)}"}, status_code=500)


@router.get("/api/wechat_contacts/ensure_contact_cache")
def wechat_contacts_ensure_cache():
    from app.application.facades.wechat_facade import refresh_wechat_contacts_from_decrypt

    payload, code = refresh_wechat_contacts_from_decrypt()
    return JSONResponse(payload, status_code=code)


@router.post("/api/wechat_contacts/ensure_contact_cache")
def wechat_contacts_ensure_contact_cache_post():
    from app.application.facades.wechat_facade import refresh_wechat_contacts_from_decrypt

    payload, code = refresh_wechat_contacts_from_decrypt()
    return JSONResponse(payload, status_code=code)


@router.get("/api/wechat_contacts/message_source_size")
def wechat_contacts_message_source_size():
    from app.application.facades.wechat_facade import wechat_message_source_size_payload

    payload, code = wechat_message_source_size_payload()
    return JSONResponse(payload, status_code=code)


@router.post("/api/wechat_contacts/send_message")
def wechat_contacts_send_message(body: dict = Body(default_factory=dict)):
    try:
        contact_name = (body.get("contact_name") or "").strip()
        message = (body.get("message") or "").strip()
        if not contact_name:
            return JSONResponse(
                {"success": False, "message": "联系人名称不能为空"}, status_code=400
            )
        if not message:
            return JSONResponse({"success": False, "message": "消息内容不能为空"}, status_code=400)

        from app.utils.path_utils import get_resource_path

        sys_path = get_resource_path("wechat-decrypt")
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)

        from resources.wechat_cv.wechat_cv_send import search_and_send_by_cv

        result = search_and_send_by_cv(contact_name, message, delay=1.0, use_ocr=True)
        if result.get("status") == "success":
            return {"success": True, "message": f"已发送给 {contact_name}", "result": result}
        return JSONResponse(
            {
                "success": False,
                "message": f"发送失败: {result.get('message', '未知错误')}",
                "result": result,
            },
            status_code=500,
        )
    except Exception as e:
        logger.exception("wechat_contacts send_message: %s", e)
        return JSONResponse({"success": False, "message": f"发送失败：{str(e)}"}, status_code=500)


@router.post("/api/wechat_contacts/{contact_id}/send_message")
def wechat_contacts_send_message_to_id(contact_id: int, body: dict = Body(default_factory=dict)):
    try:
        message = (body.get("message") or "").strip()
        if not message:
            return JSONResponse({"success": False, "message": "消息内容不能为空"}, status_code=400)

        from app.application import get_wechat_contact_app_service

        service = get_wechat_contact_app_service()
        contact = service.get_contact_by_id(contact_id)
        if not contact:
            return JSONResponse(
                {"success": False, "message": f"联系人不存在: {contact_id}"}, status_code=404
            )

        contact_name = (
            contact.get("contact_name")
            or contact.get("remark")
            or contact.get("wechat_id")
            or f"ID {contact_id}"
        )

        from app.utils.path_utils import get_resource_path

        sys_path = get_resource_path("wechat-decrypt")
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)

        from resources.wechat_cv.wechat_cv_send import search_and_send_by_cv

        result = search_and_send_by_cv(contact_name, message, delay=1.0, use_ocr=True)
        if result.get("status") == "success":
            return {"success": True, "message": f"已发送给 {contact_name}", "result": result}
        return JSONResponse(
            {
                "success": False,
                "message": f"发送失败: {result.get('message', '未知错误')}",
                "result": result,
            },
            status_code=500,
        )
    except Exception as e:
        logger.exception("wechat_contacts send to id: %s", e)
        return JSONResponse({"success": False, "message": f"发送失败：{str(e)}"}, status_code=500)
