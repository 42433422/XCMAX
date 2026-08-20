# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


@_facade().extension_router.get("/im/cs/inbox/{conversation_id}/messages")
async def mobile_im_cs_inbox_messages(
    conversation_id: int,
    request: _facade().Request,
    user=_facade().Depends(_facade().get_mobile_user),
):
    """运营者手机:读某客服会话历史(fromCustomer 区分客户/客服)。"""
    _, err = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            svc = ImApplicationService(db)
            cs_id = int(svc.enterprise_cs_user_id() or 0)
            raw = svc.cs_inbox_messages(conversation_id)
        messages = [
            {
                "messageId": str(m.get("id") or ""),
                "fromCustomer": int(m.get("sender_user_id") or 0) != cs_id,
                "senderName": str(m.get("sender_display_name") or ""),
                "body": str(m.get("body") or ""),
                "timestamp": str(m.get("created_at") or ""),
            }
            for m in raw
        ]
        return _facade().format_mobile_response(data={"messages": messages})
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile cs inbox messages failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "客服消息加载失败", success=False, code=500),
            status_code=500,
        )


@_facade().extension_router.post("/im/cs/inbox/{conversation_id}/reply")
async def mobile_im_cs_inbox_reply(
    conversation_id: int,
    body: dict,
    request: _facade().Request,
    user=_facade().Depends(_facade().get_mobile_user),
):
    """运营者手机:以「企业专属客服」身份回复客户。"""
    _, err = _facade()._require_mobile_admin(request, user)
    if err is not None:
        return err
    text = str(body.get("body") or "").strip()
    if not text:
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "消息不能为空", success=False, code=400),
            status_code=400,
        )
    from app.application.im_app_service import ImApplicationService
    from app.db.session import get_db

    try:
        with get_db() as db:
            result = ImApplicationService(db).cs_reply(conversation_id, text)
        sent = result.get("message") or {}
        return _facade().format_mobile_response(
            data={
                "messageId": str(sent.get("id") or ""),
                "timestamp": str(sent.get("created_at") or ""),
            }
        )
    except (ValueError, PermissionError):
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "回复内容无效", success=False, code=400),
            status_code=400,
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("mobile cs inbox reply failed")
        return _facade().JSONResponse(
            _facade().format_mobile_response(None, "客服回复失败", success=False, code=500),
            status_code=500,
        )
