"""XCmax admin token usage route."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import app.fastapi_routes.xcmax_admin_patch as _p

router = APIRouter()

@router.get("/admin/token-usage", response_model=None)
async def admin_token_usage(request: Request):
    """Token 用量聚合：本地账本 + Cursor + Codex + Trae。"""
    from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

    if not _session_id_from_request(request):
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    return await asyncio.to_thread(_p._build_token_usage_summary)
