"""AI 业务数据 Tab · 三端终端（网站 / 软件 / App）路由。

仪表盘 ``docs/xcagi-dashboard/mon-ai-biz.js`` 调用：
  GET /api/xcmax/aibiz/web-terminal   — P-W 网站 surface-audit（远端 MODstore）
  GET /api/xcmax/aibiz/desk-terminal  — P-S 软件 surface-audit（本地企业版客户端）
  GET /api/xcmax/aibiz/app-terminal   — P-App 移动 surface-audit（adb 模拟器原生屏）
  GET /api/xcmax/aibiz/surface-image  — 单页 PNG 直出（terminal/index/view）
  GET /api/xcmax/aibiz/surface-page   — 单页元数据（含 b64 / saved 路径）

实现委托 ``app.application.aibiz_web_terminal_service``；鉴权在 service 内解析
（当前会话 market JWT → XCAGI_AIBIZ_MARKET_* 服务账号 → 演示号回退）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.application.aibiz_web_terminal_service import (
    build_terminal_payload,
    fetch_surface_page_payload,
    serve_surface_image,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax/aibiz", tags=["aibiz-terminal"])


@router.get("/web-terminal")
async def aibiz_web_terminal(
    request: Request,
    refresh: bool = Query(False),
    compact: bool = Query(True),
):
    return await build_terminal_payload(
        request, terminal="web", refresh=refresh, compact=compact
    )


@router.get("/desk-terminal")
async def aibiz_desk_terminal(
    request: Request,
    refresh: bool = Query(False),
    compact: bool = Query(True),
):
    return await build_terminal_payload(
        request, terminal="software", refresh=refresh, compact=compact
    )


@router.get("/app-terminal")
async def aibiz_app_terminal(
    request: Request,
    refresh: bool = Query(False),
    compact: bool = Query(True),
):
    return await build_terminal_payload(
        request, terminal="app", refresh=refresh, compact=compact
    )


@router.get("/surface-image")
async def aibiz_surface_image(
    request: Request,
    terminal: str = Query("web"),
    index: int = Query(0, ge=0),
    view: str = Query(""),
) -> Response:
    return await serve_surface_image(
        request, terminal=terminal, index=index, view=view
    )


@router.get("/surface-page", response_model=None)
async def aibiz_surface_page(
    request: Request,
    terminal: str = Query("web"),
    index: int = Query(0, ge=0),
):
    return await fetch_surface_page_payload(request, terminal=terminal, index=index)
