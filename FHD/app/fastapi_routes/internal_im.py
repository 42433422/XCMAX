"""内部 IM 投递端点（员工→老板 1:1 IM 聊天页）。

独立精简 router：仅依赖 ``ImApplicationService``（只 import IM 模型 + User），避开 im_routes
那条较重的依赖链（execution_scope/workspaces/super_employee 等），确保在精简/陈旧部署上也能挂载。

供 MODstore（phase-D 不确定性问答 / 员工主动汇报）经 ``X-Internal-Api-Key`` 服务端调用：
让员工的话作为「该员工发来的 IM 消息」出现在老板与其的 1:1 会话里（员工真正长出嘴）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.application.im_app_service import ImApplicationService, ensure_im_tables
from app.db import HostSessionLocal, get_host_engine
from app.fastapi_routes.mobile_api import get_mobile_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["internal-im"])


def _mobile_uid(user: Any) -> int:
    for attr in ("id", "user_id"):
        try:
            v = int(getattr(user, attr, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            return v
    return 0


def _internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()


@router.post("/api/internal/im/employee-message")
async def internal_employee_message(
    request: Request,
    body: dict = Body(default_factory=dict),
) -> Any:
    """以某 AI 员工身份，把一条消息投进老板的 1:1 IM 会话。

    Body: ``{boss_user_id, employee_id, body, display_name?}``。需 ``X-Internal-Api-Key``。
    """
    expected = _internal_api_key()
    provided = (request.headers.get("X-Internal-Api-Key") or "").strip()
    if not expected or provided != expected:
        return JSONResponse({"success": False, "message": "unauthorized"}, status_code=401)
    try:
        boss_user_id = int(body.get("boss_user_id") or body.get("user_id") or 0)
    except (TypeError, ValueError):
        boss_user_id = 0
    employee_id = str(body.get("employee_id") or "").strip()
    text = str(body.get("body") or body.get("text") or "").strip()
    display_name = str(body.get("display_name") or "").strip()
    if boss_user_id <= 0 or not employee_id or not text:
        return JSONResponse(
            {"success": False, "message": "boss_user_id/employee_id/body required"},
            status_code=400,
        )
    try:
        ensure_im_tables(get_host_engine())
        db = HostSessionLocal()
        try:
            result = ImApplicationService(db).post_employee_message(
                boss_user_id=boss_user_id,
                employee_id=employee_id,
                body=text,
                display_name=display_name,
            )
        finally:
            db.close()
        if not result:
            return JSONResponse({"success": False, "message": "post failed"}, status_code=400)
        # 实时推送（best-effort，不可用也不影响：消息已落库并经 sync 投递）。
        try:
            from app.infrastructure.im.ws_hub import im_ws_hub

            conversation_id = int(result["conversation_id"])
            payload = {
                "type": "im.message",
                "conversation_id": conversation_id,
                "message": result["message"],
                "updated_at_ms": result.get("updated_at_ms"),
            }
            await im_ws_hub.send_to_user(int(boss_user_id), payload)
            await im_ws_hub.send_to_user(
                int(boss_user_id),
                {
                    "type": "message",
                    "conversation_id": conversation_id,
                    "message": result["message"],
                },
            )
        except RECOVERABLE_ERRORS:
            logger.debug("internal employee-message ws push skipped", exc_info=True)
        return {"success": True, **result}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("internal_employee_message")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


# ── 手机 IM 屏所需端点（精简 router 内置，绕开 im_routes 依赖链，保证陈旧部署可用）──


@router.get("/api/im/conversations")
def im_list_conversations(user: Any = Depends(get_mobile_user)) -> Any:
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        return {"success": True, "conversations": ImApplicationService(db).list_conversations(uid)}
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_list_conversations")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/direct")
def im_create_direct(
    body: dict = Body(default_factory=dict), user: Any = Depends(get_mobile_user)
) -> Any:
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    peer = int(body.get("peer_user_id") or 0)
    if peer <= 0:
        return JSONResponse({"success": False, "message": "peer_user_id 无效"}, status_code=400)
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        return {"success": True, "conversation": ImApplicationService(db).get_or_create_direct(uid, peer)}
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_create_direct")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.get("/api/im/conversations/{conversation_id}/messages")
def im_list_messages(
    conversation_id: int,
    user: Any = Depends(get_mobile_user),
    limit: int = Query(default=50, ge=1, le=100),
) -> Any:
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        return {
            "success": True,
            "messages": ImApplicationService(db).list_messages(conversation_id, uid, limit=limit),
        }
    except PermissionError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_list_messages")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()


@router.post("/api/im/conversations/{conversation_id}/messages")
def im_post_message(
    conversation_id: int,
    body: dict = Body(default_factory=dict),
    user: Any = Depends(get_mobile_user),
) -> Any:
    uid = _mobile_uid(user)
    if uid <= 0:
        return JSONResponse({"success": False, "message": "未授权"}, status_code=401)
    ensure_im_tables(get_host_engine())
    db = HostSessionLocal()
    try:
        result = ImApplicationService(db).send_message(
            conversation_id, uid, str(body.get("body") or "")
        )
        return {"success": True, **result}
    except PermissionError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("im_post_message")
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)
    finally:
        db.close()
