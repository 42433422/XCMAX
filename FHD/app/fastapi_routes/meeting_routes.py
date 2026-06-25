"""会议纪要 SSOT API — HTTP 薄层，委托 meeting_minutes_app_service。

- ``router``        : Web/桌面 ``/api/meetings/*``（X-User-Id 头取归属）。
- ``mobile_router`` : 三端原生 ``/api/mobile/v1/meetings/*``（移动 JWT 鉴权 + 统一响应壳）。
两者共用同一应用服务与三级派生内核；转写各端自取后把 transcript 文本喂进 ``generate-all``。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.utils.mobile_api import format_mobile_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])
mobile_router = APIRouter(prefix="/api/mobile/v1/meetings", tags=["mobile-meetings"])


class GenerateRequest(BaseModel):
    raw_transcript: str = Field(..., description="会议转写原文（录音转写后的纯文本）")
    title: Optional[str] = Field(default=None, description="会议标题（可选）")


def _svc():
    from app.application import meeting_minutes_app_service as svc

    return svc


def _web_user_id(request: Request, payload_user_id: Any = None) -> Optional[int]:
    raw = request.headers.get("X-User-Id") or request.headers.get("X-User-ID") or payload_user_id
    try:
        return int(raw) if raw is not None and str(raw).strip() else None
    except (TypeError, ValueError):
        return None


# ── Web / 桌面 ─────────────────────────────────────────────────────────────


@router.get("/levels")
async def get_levels() -> dict[str, Any]:
    """返回三级定义（标签/派生关系），前端据此渲染 Tab。"""
    from app.services.meeting_minutes.pipeline import load_levels_config

    return {"success": True, "data": load_levels_config()}


@router.post("/generate-all")
async def generate_all(req: GenerateRequest, request: Request) -> dict[str, Any]:
    """一次性生成三级会议纪要（剧本式 → 架构图式 → 说人话）。"""
    if not (req.raw_transcript or "").strip():
        raise HTTPException(status_code=400, detail="会议原文为空")
    data = await _svc().create_and_generate(
        req.raw_transcript, title=req.title, user_id=_web_user_id(request)
    )
    return {"success": True, "data": data}


@router.get("/{minute_id}")
async def get_one(minute_id: int, request: Request) -> dict[str, Any]:
    data = _svc().get_minute(minute_id, user_id=_web_user_id(request))
    if data is None:
        raise HTTPException(status_code=404, detail="会议纪要不存在")
    return {"success": True, "data": data}


@router.get("")
async def list_all(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    data = _svc().list_minutes(user_id=_web_user_id(request), page=page, per_page=per_page)
    return {"success": True, "data": data}


# ── 三端原生（移动 JWT）────────────────────────────────────────────────────


def _mobile_uid(authorization: Optional[str]) -> Optional[int]:
    from app.security.mobile_jwt import user_id_from_mobile_bearer

    return user_id_from_mobile_bearer(authorization)


@mobile_router.get("/levels")
async def mobile_levels() -> dict[str, Any]:
    from app.services.meeting_minutes.pipeline import load_levels_config

    return format_mobile_response(data=load_levels_config())


@mobile_router.post("/generate-all")
async def mobile_generate(
    req: GenerateRequest, authorization: Optional[str] = Header(default=None)
) -> dict[str, Any]:
    uid = _mobile_uid(authorization)
    if uid is None:
        return format_mobile_response(data=None, message="未授权", success=False, code=401)
    if not (req.raw_transcript or "").strip():
        return format_mobile_response(data=None, message="会议原文为空", success=False, code=400)
    data = await _svc().create_and_generate(req.raw_transcript, title=req.title, user_id=uid)
    return format_mobile_response(data=data)


@mobile_router.get("/{minute_id}")
async def mobile_get_one(
    minute_id: int, authorization: Optional[str] = Header(default=None)
) -> dict[str, Any]:
    uid = _mobile_uid(authorization)
    if uid is None:
        return format_mobile_response(data=None, message="未授权", success=False, code=401)
    data = _svc().get_minute(minute_id, user_id=uid)
    if data is None:
        return format_mobile_response(data=None, message="会议纪要不存在", success=False, code=404)
    return format_mobile_response(data=data)


@mobile_router.get("")
async def mobile_list(
    authorization: Optional[str] = Header(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    uid = _mobile_uid(authorization)
    if uid is None:
        return format_mobile_response(data=None, message="未授权", success=False, code=401)
    data = _svc().list_minutes(user_id=uid, page=page, per_page=per_page)
    return format_mobile_response(data=data)
