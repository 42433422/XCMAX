"""Qclaw 兼容路由（已升级为 AIOPEN，URL 契约保持不变）。

Phase 2C 从 :mod:`app.fastapi_routes.archive_gap_batch1/2` 拆分而出；现 Qclaw
龙虾生态已升级为 AIOPEN 开放平台（:mod:`app.fastapi_routes.ai_open`），本模块
仅保留旧 URL 兼容：

- ``GET /api/ai/qclaw/routes`` / ``GET /api/ai/qclaw/panel``
- ``POST /api/ai/qclaw/wechat-gateway``
- ``POST /api/ai/qclaw/openclaw/config``
- ``POST /api/ai/qclaw/whitelist``
- ``POST /api/ai/qclaw/test-route``
- ``POST /api/ai/qclaw/openclaw/chat``

运行时状态 SSOT 已迁至 :data:`app.application.aiopen.service.AIOPEN_STATE`；
``_QCLOW_RUNTIME_STATE`` 保留为其别名，旧 batch2（wechat 相关）导入不受影响。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from app.application.aiopen.service import AIOPEN_STATE, openclaw_chat_proxy
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai-qclaw"])

# 兼容别名：旧代码 `from app.fastapi_routes.ai_qclaw import _QCLOW_RUNTIME_STATE`
_QCLOW_RUNTIME_STATE: dict[str, Any] = AIOPEN_STATE


@router.get("/api/ai/qclaw/routes")
def ai_qclaw_routes():
    return {
        "success": True,
        "source": "qclaw",
        "permissions": {
            "normal_routes": [
                "/api/ai/unified_chat",
                "/api/tools/execute",
                "/api/products/*",
                "/api/customers/*",
                "/api/materials/*",
            ],
            "pro_routes": [
                "/api/ai/chat",
                "/api/ai/chat/stream",
                "/api/wechat/*",
                "/api/wechat_contacts/*",
                "/api/shipment/*",
                "/api/print/*",
            ],
        },
        "note": "Qclaw/AIOPEN 来源允许同时访问普通版与专业版主链路。",
    }


@router.get("/api/ai/qclaw/panel")
def ai_qclaw_panel():
    whitelist = _QCLOW_RUNTIME_STATE.get("whitelist", {})
    routes = [{"path": path, "enabled": bool(enabled)} for path, enabled in whitelist.items()]
    return {
        "success": True,
        "wechat_open": bool(_QCLOW_RUNTIME_STATE.get("wechat_open", False)),
        "openclaw_base": str(_QCLOW_RUNTIME_STATE.get("openclaw_base", "http://127.0.0.1:28789")),
        "routes": routes,
    }


@router.post("/api/ai/qclaw/wechat-gateway")
def ai_qclaw_wechat_gateway(body: dict = Body(default_factory=dict)):
    enabled = bool(body.get("enabled", False))
    _QCLOW_RUNTIME_STATE["wechat_open"] = enabled
    return {"success": True, "wechat_open": enabled}


@router.post("/api/ai/qclaw/openclaw/config")
def ai_qclaw_openclaw_config(body: dict = Body(default_factory=dict)):
    base_url = str(body.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        return JSONResponse({"success": False, "message": "base_url 不能为空"}, status_code=400)
    _QCLOW_RUNTIME_STATE["openclaw_base"] = base_url
    return {"success": True, "openclaw_base": base_url}


@router.post("/api/ai/qclaw/whitelist")
def ai_qclaw_whitelist(body: dict = Body(default_factory=dict)):
    path = str(body.get("path") or "").strip()
    enabled = bool(body.get("enabled", False))
    if not path:
        return JSONResponse({"success": False, "message": "path 不能为空"}, status_code=400)
    whitelist = _QCLOW_RUNTIME_STATE.setdefault("whitelist", {})
    whitelist[path] = enabled
    return {"success": True, "path": path, "enabled": enabled}


@router.post("/api/ai/qclaw/test-route")
def ai_qclaw_test_route(request: Request, body: dict = Body(default_factory=dict)):
    path = str(body.get("path") or "").strip()
    method = str(body.get("method") or "GET").upper()
    if not path:
        return JSONResponse({"success": False, "message": "path 不能为空"}, status_code=400)
    whitelist = _QCLOW_RUNTIME_STATE.get("whitelist", {})
    if not bool(whitelist.get(path, False)):
        return JSONResponse({"success": False, "message": "该路由未在白名单启用"}, status_code=403)
    try:
        client = TestClient(request.app)
        if method == "POST":
            resp = client.post(path, json={"source": "qclaw", "message": "smoke"})
        else:
            resp = client.get(path)
        ok = resp.status_code < 500
        return {
            "success": True,
            "path": path,
            "method": method,
            "status_code": resp.status_code,
            "result": "ok" if ok else "error",
        }
    except RECOVERABLE_ERRORS as err:
        return JSONResponse(
            {"success": False, "path": path, "method": method, "message": str(err)},
            status_code=500,
        )


@router.post("/api/ai/qclaw/openclaw/chat")
def ai_qclaw_openclaw_chat(body: dict = Body(default_factory=dict)):
    message = str(body.get("message") or "").strip()
    if not message:
        return JSONResponse({"success": False, "message": "message 不能为空"}, status_code=400)
    payload, status = openclaw_chat_proxy(message)
    if status == 200:
        return payload
    return JSONResponse(payload, status_code=status)
