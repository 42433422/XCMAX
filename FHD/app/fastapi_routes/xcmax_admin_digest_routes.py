"""XCmax admin digest routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
import app.fastapi_routes.xcmax_admin_patch as _p

router = APIRouter()

@router.get("/admin/digest-identity", response_model=None)
async def get_digest_identity(request: Request):
    """透传远端「身份校验码」摘要；与修茈市场 ``verify-admin-digest-code`` 同一实现源。"""
    from app.fastapi_routes.market_account import _market_base_url

    api_base = _market_base_url()
    out = await _p._market_admin_proxy(
        request,
        "GET",
        "/api/xcmax/admin/digest-identity",
    )
    # 旧版或未挂载 xcmax_admin 的 MODstore 会对该路径返回 404；此处降级为 200 + 空 code，
    # 与前端 ServerFunctionsView「摘要 HTML 后备」一致，并避免控制台对可选接口报红。
    if isinstance(out, JSONResponse) and out.status_code == 404:
        logger.debug(
            "digest-identity: upstream 404, returning empty code payload for HTML fallback"
        )
        return {
            "success": True,
            "data": {
                "code": "",
                "expires_at": "",
                "valid": False,
                "daily_digest_id": None,
                "digest_api_base": api_base,
            },
        }
    if isinstance(out, dict):
        return _p._inject_digest_api_base(out, api_base)
    return out
@router.get("/admin/daily-digests", response_model=None)
async def list_daily_digests(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """从服务器读取已保存的每日摘要邮件副本。"""
    return await _p._digest_local_or_proxy(
        request,
        "GET",
        f"/api/agent/butler/daily-digests?limit={limit}&offset={offset}",
    )

@router.get("/admin/daily-digests/{record_id}", response_model=None)
async def get_daily_digest(request: Request, record_id: int):
    """从服务器读取单条每日摘要完整正文。"""
    return await _p._digest_local_or_proxy(
        request,
        "GET",
        f"/api/agent/butler/daily-digests/{record_id}",
    )

@router.get("/admin/daily-digests/{record_id}/artifacts", response_model=None)
async def get_daily_digest_artifacts(request: Request, record_id: int):
    """日更各阶段产物清单（截图 / PPT / digest HTML 等）。"""
    return await _p._digest_local_or_proxy(
        request,
        "GET",
        f"/api/agent/butler/daily-digests/{record_id}/artifacts",
    )

@router.get("/admin/action-items", response_model=None)
async def list_action_items(
    request: Request,
    kind: str = Query("", description="patch | update"),
    day: str = Query("", description="YYYY-MM-DD"),
):
    """Vibe 预备双清单结构化条目（patch / update）。"""
    q = []
    if kind:
        q.append(f"kind={kind}")
    if day:
        q.append(f"day={day}")
    query = ("?" + "&".join(q)) if q else ""
    return await _p._digest_local_or_proxy(request, "GET", f"/api/admin/action-items{query}")

@router.get("/admin/action-items/stats", response_model=None)
async def action_items_stats(
    request: Request,
    kind: str = Query("", description="patch | update"),
    day: str = Query("", description="YYYY-MM-DD"),
):
    """行动条目完成率 / 分布。"""
    q = []
    if kind:
        q.append(f"kind={kind}")
    if day:
        q.append(f"day={day}")
    query = ("?" + "&".join(q)) if q else ""
    return await _p._digest_local_or_proxy(request, "GET", f"/api/admin/action-items/stats{query}")

@router.post("/admin/daily-digests/{record_id}/vibe-prep/sessions", response_model=None)
async def start_digest_vibe_prep_session(
    request: Request,
    record_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """基于每日摘要生成 Vibe-Coding 预备 Markdown（更新 + 补丁）后台会话。"""
    return await _p._market_admin_proxy(
        request,
        "POST",
        f"/api/agent/butler/daily-digests/{record_id}/vibe-prep/sessions",
        json_body=body,
    )

@router.post("/admin/daily-digests/{record_id}/line-execute", response_model=None)
async def start_digest_line_execute(
    request: Request,
    record_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """Phase A：消费 P-S（或指定产线）补丁清单并派发员工子任务。"""
    return await _p._market_admin_proxy(
        request,
        "POST",
        f"/api/agent/butler/daily-digests/{record_id}/line-execute",
        json_body=body,
    )

@router.get("/admin/digest-vibe-prep/sessions/{session_id}", response_model=None)
async def get_digest_vibe_prep_session(request: Request, session_id: str):
    """轮询 Vibe 预备文档生成会话（复用 workbench session 存储）。"""
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        return JSONResponse({"success": False, "message": "session_id 必填"}, status_code=400)
    return await _p._market_admin_proxy(
        request,
        "GET",
        f"/api/workbench/sessions/{sid}",
    )

@router.post("/admin/all-hands-report/sessions", response_model=None)
async def start_all_hands_report_session(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """启动服务器员工大会后台会话，返回远端 session_id。"""
    return await _p._market_admin_proxy(
        request,
        "POST",
        "/api/agent/butler/all-hands-report/sessions",
        json_body=body,
    )

@router.get("/admin/all-hands-report/sessions/{session_id}", response_model=None)
async def get_all_hands_report_session(request: Request, session_id: str):
    """轮询服务器员工大会后台会话。"""
    sid = "".join(ch for ch in str(session_id or "") if ch.isalnum())[:64]
    if not sid:
        return JSONResponse({"success": False, "message": "session_id 必填"}, status_code=400)
    return await _p._market_admin_proxy(
        request,
        "GET",
        f"/api/workbench/sessions/{sid}",
    )
