"""服务间：MODstore 员工执行管道 → FHD IM 推送。

MODstore 后端在员工执行管道的关键节点（cognition/verification/handoff/Phase-D ask）
调本 endpoint，让员工在 IM 系统里像真人一样主动给老板发一条消息。

鉴权：复用 `_require_internal_api_key`（参考 payment_reconcile_internal_api.py），
通过 `X-Internal-Api-Key` header 校验，env `FHD_INTERNAL_API_KEY`（或备用 env）。
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal/employee-im", tags=["employee-im-internal"])


def _require_internal_api_key(request: Request) -> None:
    expected = (
        os_get_env("FHD_INTERNAL_API_KEY")
        or os_get_env("XCAGI_MARKET_INTERNAL_API_KEY")
        or os_get_env("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    )
    if not expected:
        raise HTTPException(status_code=503, detail="internal api not configured")
    got = (request.headers.get("x-internal-api-key") or "").strip()
    if not got or not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=403, detail="invalid internal api key")


def os_get_env(key: str) -> str:
    import os

    return (os.environ.get(key) or "").strip()


class EmployeeImSendRequest(BaseModel):
    boss_user_id: int = Field(
        0,
        description="老板 user_id；<=0 时 FHD 自动查 owner_user_id 表，再回退 env FHD_BOSS_USER_ID",
    )
    employee_id: str = Field(..., min_length=1, description="员工 ID（如 llm-ops-engineer）")
    mod_id: str = Field("", description="员工所属 mod_id")
    display_name: str = Field("", description='员工显示名（如 "LLM 运维工程师"）')
    avatar_url: str = Field("", description="员工头像 URL")
    body: str = Field(..., min_length=1, description="消息正文")
    hook: str = Field("", description="触发源标记（cognition/verification/handoff/ask）")
    owner_user_id: int = Field(
        0, description="可选；>0 时把员工 owner 设成这个 user_id（per-employee owner 表）"
    )


def _resolve_boss_uid(svc, payload: EmployeeImSendRequest) -> int:
    """优先级：payload.boss_user_id > AiEmployeeProfile.owner_user_id > env FHD_BOSS_USER_ID。"""
    bid = int(payload.boss_user_id or 0)
    if bid > 0:
        return bid
    bid = svc.get_employee_owner(payload.employee_id)
    if bid > 0:
        return bid
    raw = (os_get_env("FHD_BOSS_USER_ID") or "").strip()
    try:
        bid = int(raw) if raw else 0
    except ValueError:
        bid = 0
    return bid


@router.post("/send")
async def employee_im_send(request: Request, payload: EmployeeImSendRequest = Body(...)):
    """员工 → 老板 IM 消息推送。

    内部流程：
        1. `_require_internal_api_key` 鉴权
        2. 解析 boss_user_id：payload > per-employee owner 表 > env FHD_BOSS_USER_ID
        3. `ImApplicationService.send_employee_message(boss_uid, employee_id, body, ...)`
           — 自动 ensure 虚拟员工 User 行 + 建/复用 direct 会话 + 写 im_messages
        4. 对所有会话成员（除发送者员工本人）调 `im_ws_hub.send_to_user` 实时推 WS，
           复用路由层 `im_send_message` 的推送范式（员工像真人一样在线时即时收到）

    返回 conversation_id / message / member_user_ids 给调用方（MODstore 仅用于日志）。
    """
    _require_internal_api_key(request)

    try:
        from app.application.im_app_service import ImApplicationService
        from app.db import SessionLocal

        db = SessionLocal()
    except ImportError as exc:
        logger.exception("employee_im_send 缺少依赖：%s", exc)
        return JSONResponse(
            {"success": False, "message": f"server misconfigured: {exc}"}, status_code=500
        )

    try:
        svc = ImApplicationService(db)
        boss_uid = _resolve_boss_uid(svc, payload)
        if boss_uid <= 0:
            return JSONResponse(
                {
                    "success": False,
                    "message": "boss_user_id 未配：payload/owner 表/env FHD_BOSS_USER_ID 都为空",
                },
                status_code=400,
            )
        result: dict[str, Any] = svc.send_employee_message(
            boss_uid=boss_uid,
            employee_id=str(payload.employee_id).strip(),
            body=payload.body,
            mod_id=payload.mod_id,
            display_name=payload.display_name,
            avatar_url=payload.avatar_url,
            owner_user_id=int(payload.owner_user_id or 0),
        )
        # WS 实时推送：复用 im_routes.py:im_send_message 的推送范式，
        # 让在线的老板（以及其他成员）即时收到员工主动消息。
        try:
            from app.fastapi_routes.im_routes import im_ws_hub

            conv_id = int(result.get("conversation_id") or 0)
            sender_uid = int(result.get("employee_user_id") or 0)
            message = result.get("message") or {}
            updated_at_ms = result.get("updated_at_ms")
            member_ids = [int(m) for m in (result.get("member_user_ids") or [])]
            legacy_payload = {
                "type": "message",
                "conversation_id": conv_id,
                "message": message,
            }
            sync_payload = {
                "type": "im.message",
                "conversation_id": conv_id,
                "message": message,
                "updated_at_ms": updated_at_ms,
            }
            for member_id in member_ids:
                if member_id == sender_uid:
                    continue
                await im_ws_hub.send_to_user(member_id, legacy_payload)
                await im_ws_hub.send_to_user(member_id, sync_payload)
        except Exception:  # noqa: BLE001 - websocket fanout is best-effort after DB write
            logger.debug("employee_im_send ws push skipped", exc_info=True)

        logger.info(
            "employee_im_send ok: boss=%s employee=%s hook=%s conv=%s",
            boss_uid,
            payload.employee_id,
            payload.hook,
            result.get("conversation_id"),
        )
        return JSONResponse({"success": True, "data": result, "boss_user_id": boss_uid})
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception(
            "employee_im_send failed: boss=%s employee=%s hook=%s err=%s",
            payload.boss_user_id,
            payload.employee_id,
            payload.hook,
            exc,
        )
        return JSONResponse({"success": False, "message": f"推送失败：{exc}"}, status_code=500)
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001 - closing a request-scoped DB session must not mask response
            pass


class EmployeeImSetOwnerRequest(BaseModel):
    employee_id: str = Field(..., min_length=1)
    owner_user_id: int = Field(..., gt=0)


@router.post("/set-owner")
def employee_im_set_owner(request: Request, payload: EmployeeImSetOwnerRequest = Body(...)):
    """设置员工的专属老板 user_id（per-employee owner 表）。

    需要员工档案已存在（先调过 send 至少一次会自动建档案）。
    后续 notify_boss 不传 boss_user_id 时，FHD 会自动用这个 owner。
    """
    _require_internal_api_key(request)
    try:
        from app.application.im_app_service import ImApplicationService
        from app.db import SessionLocal

        db = SessionLocal()
    except ImportError as exc:
        return JSONResponse(
            {"success": False, "message": f"server misconfigured: {exc}"}, status_code=500
        )
    try:
        svc = ImApplicationService(db)
        ok = svc.set_employee_owner(
            str(payload.employee_id).strip(),
            int(payload.owner_user_id),
        )
        if not ok:
            return JSONResponse(
                {"success": False, "message": "员工档案不存在或 owner 无效"},
                status_code=404,
            )
        return JSONResponse({"success": True})
    except ValueError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=400)
    except Exception as exc:
        logger.exception("employee_im_set_owner failed: %s", exc)
        return JSONResponse({"success": False, "message": f"设置失败：{exc}"}, status_code=500)
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001 - closing a request-scoped DB session must not mask response
            pass
