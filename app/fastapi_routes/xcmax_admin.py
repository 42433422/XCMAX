"""XCmax 服务器后台控制面路由。

提供:
  GET  /api/xcmax/admin/modules      — 本地模块注册表（核心 + Mod + 员工包）
  GET  /api/xcmax/admin/remote-status — 远端服务器连接状态探测
  GET  /api/xcmax/sync/status        — 双向同步健康状态
  POST /api/xcmax/sync/push          — 触发本地 outbox 向服务器推送
  GET  /api/xcmax/sync/changes       — 获取变更日志（支持 since_cursor）
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import datetime
from typing import Any

import asyncio

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/xcmax", tags=["xcmax-admin"])

REMOTE_HOST = os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
REMOTE_PORT = int(os.environ.get("XCMAX_REMOTE_PORT", "9999"))


def _require_market_admin_session(request: Request) -> JSONResponse | None:
    from app.application.session_account_meta import load_session_account_meta
    from app.fastapi_routes.legacy_helpers import _session_id_from_request

    sid = _session_id_from_request(request)
    if not sid:
        return JSONResponse(
            {"success": False, "message": "请先登录"},
            status_code=401,
        )
    meta = load_session_account_meta(sid) or {}
    if meta.get("account_kind") != "admin" or not meta.get("market_is_admin"):
        return JSONResponse(
            {"success": False, "message": "需要管理员账号登录后访问"},
            status_code=403,
        )
    return None


async def _market_admin_proxy(
    request: Request,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    require_admin_session: bool = True,
):
    """Proxy server-function calls through the market token bound to the local session."""
    if require_admin_session:
        gate = _require_market_admin_session(request)
        if gate is not None:
            return gate
    try:
        from app.fastapi_routes.market_account import (
            _authorization_from_request,
            _error_message,
            _proxy_json,
        )
    except Exception as exc:
        return JSONResponse(
            {"success": False, "message": f"市场账号代理不可用: {exc}"},
            status_code=500,
        )

    body_for_auth = json_body if isinstance(json_body, dict) else {}
    authorization = _authorization_from_request(request, body_for_auth)
    if not authorization:
        return JSONResponse(
            {"success": False, "message": "尚未绑定修茈服务器账号；请重新登录或在设置中同步市场 Authorization"},
            status_code=401,
        )

    payload = await _proxy_json(
        method,
        path,
        json_body=json_body,
        authorization=authorization,
        return_error_payload=True,
    )
    if isinstance(payload, JSONResponse):
        return payload
    if isinstance(payload, dict) and payload.get("__proxy_error__"):
        status_code = int(payload.get("status_code") or 502)
        raw_error = payload.get("payload")
        return JSONResponse(
            {"success": False, "message": _error_message(raw_error, status_code), "data": raw_error},
            status_code=status_code,
        )
    return payload


# ---------------------------------------------------------------------------
# 核心功能模块定义（与前端 Sidebar.menuItemsBase 对齐）
# ---------------------------------------------------------------------------
CORE_MODULES = [
    {"module_id": "xcmax-admin", "display_name": "服务器后台", "route": "/xcmax-admin", "source": "core", "sync_scope": "system", "active": True, "version": "1.0"},
    {"module_id": "chat", "display_name": "智能对话", "route": "/", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "ai-ecosystem", "display_name": "智能生态", "route": "/ai-ecosystem", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "model-payment", "display_name": "模型服务", "route": "/model-payment", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "products", "display_name": "人员管理", "route": "/products", "source": "core", "sync_scope": "personnel,departments", "active": True, "version": "1.0"},
    {"module_id": "materials-list", "display_name": "班次列表", "route": "/materials-list", "source": "core", "sync_scope": "materials", "active": True, "version": "1.0"},
    {"module_id": "materials", "display_name": "服务器功能模块", "route": "/materials", "source": "core", "sync_scope": "server,digest,all_hands", "active": True, "version": "1.0"},
    {"module_id": "traditional-mode", "display_name": "表格模式", "route": "/traditional-mode", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "business-docking", "display_name": "业务对接", "route": "/business-docking", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "orders", "display_name": "考勤单管理", "route": "/orders", "source": "core", "sync_scope": "orders", "active": True, "version": "1.0"},
    {"module_id": "shipment-records", "display_name": "考勤记录", "route": "/shipment-records", "source": "core", "sync_scope": "attendance", "active": True, "version": "1.0"},
    {"module_id": "customers", "display_name": "部门管理", "route": "/customers", "source": "core", "sync_scope": "departments", "active": True, "version": "1.0"},
    {"module_id": "data-sources", "display_name": "数据来源", "route": "/data-sources", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "print", "display_name": "考勤表打印", "route": "/print", "source": "core", "sync_scope": "templates", "active": True, "version": "1.0"},
    {"module_id": "printer-list", "display_name": "打印机列表", "route": "/printer-list", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "template-preview", "display_name": "模板库", "route": "/template-preview", "source": "core", "sync_scope": "templates", "active": True, "version": "1.0"},
    {"module_id": "settings", "display_name": "系统设置", "route": "/settings", "source": "core", "sync_scope": "system", "active": True, "version": "1.0"},
    {"module_id": "tools", "display_name": "工具表", "route": "/tools", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "approval-hub", "display_name": "审批中心", "route": "/approval-hub", "source": "core", "sync_scope": "approvals", "active": True, "version": "1.0"},
    {"module_id": "other-tools", "display_name": "员工工作流", "route": "/other-tools", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
    {"module_id": "enterprise-customer-service", "display_name": "外部客服", "route": "/enterprise-customer-service", "source": "core", "sync_scope": "none", "active": True, "version": "1.0"},
]


def _collect_mod_modules() -> list[dict[str, Any]]:
    """从 mod_manager 读取已加载的本地 Mod，转换成 XCmax 模块格式。"""
    rows: list[dict[str, Any]] = []
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager
        mgr = get_mod_manager()
        if mgr is None:
            return rows
        registry = getattr(mgr, "_registry", None) or {}
        for mod_id, meta in (registry.items() if hasattr(registry, "items") else []):
            name = str(getattr(meta, "name", None) or mod_id).strip()
            version = str(getattr(meta, "version", None) or "").strip()
            rows.append({
                "module_id": str(mod_id),
                "display_name": name,
                "route": f"/mod/{mod_id}",
                "source": "local",
                "sync_scope": "module_info",
                "active": True,
                "version": version,
            })
    except Exception as exc:
        logger.debug("collect_mod_modules failed: %s", exc)
    return rows


def _collect_employee_pack_modules() -> list[dict[str, Any]]:
    """从员工包注册表读取员工包，转换成 XCmax 模块格式。"""
    rows: list[dict[str, Any]] = []
    try:
        from app.infrastructure.mods.employee_registry import EmployeeRegistry
        from app.infrastructure.mods.mod_manager import get_mod_manager
        mgr = get_mod_manager()
        mods_root = getattr(mgr, "mods_root", None) if mgr else None
        if mods_root:
            registry = EmployeeRegistry(mods_root)
            for pack in registry.list_packs():
                pack_id = str(pack.get("id") or "")
                name = str(pack.get("name") or pack_id).strip()
                rows.append({
                    "module_id": pack_id,
                    "display_name": name,
                    "route": "",
                    "source": "employee",
                    "sync_scope": "employee_pack",
                    "active": True,
                    "version": str(pack.get("version") or ""),
                })
    except Exception as exc:
        logger.debug("collect_employee_pack_modules failed: %s", exc)
    return rows


@router.get("/admin/market/users", response_model=None)
async def admin_list_market_users(request: Request):
    return await _market_admin_proxy(request, "GET", "/api/admin/users")


@router.get("/admin/market/assignable-mods", response_model=None)
async def admin_list_assignable_mods(request: Request):
    return await _market_admin_proxy(request, "GET", "/api/admin/enterprise/assignable-mods")


@router.get("/admin/market/users/{user_id}/mods", response_model=None)
async def admin_list_user_mods(request: Request, user_id: int):
    return await _market_admin_proxy(request, "GET", f"/api/admin/users/{user_id}/mods")


@router.post("/admin/market/users/{user_id}/mods/{mod_id}", response_model=None)
async def admin_bind_user_mod(request: Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action

    out = await _market_admin_proxy(
        request, "POST", f"/api/admin/users/{user_id}/mods/{mod_id}"
    )
    audit_admin_action(request, "bind_user_mod", target_user_id=user_id, mod_id=mod_id)
    return out


@router.delete("/admin/market/users/{user_id}/mods/{mod_id}", response_model=None)
async def admin_unbind_user_mod(request: Request, user_id: int, mod_id: str):
    from app.application.session_account_meta import audit_admin_action

    out = await _market_admin_proxy(
        request, "DELETE", f"/api/admin/users/{user_id}/mods/{mod_id}"
    )
    audit_admin_action(request, "unbind_user_mod", target_user_id=user_id, mod_id=mod_id)
    return out


@router.put("/admin/market/users/{user_id}/admin", response_model=None)
async def admin_set_user_admin(
    request: Request,
    user_id: int,
    is_admin: bool = Query(...),
):
    return await _market_admin_proxy(
        request, "PUT", f"/api/admin/users/{user_id}/admin?is_admin={'true' if is_admin else 'false'}"
    )


@router.put("/admin/market/users/{user_id}/enterprise", response_model=None)
async def admin_set_user_enterprise(
    request: Request,
    user_id: int,
    is_enterprise: bool = Query(...),
):
    return await _market_admin_proxy(
        request,
        "PUT",
        f"/api/admin/users/{user_id}/enterprise?is_enterprise={'true' if is_enterprise else 'false'}",
    )


@router.post("/admin/impersonate", response_model=None)
async def admin_start_impersonate(request: Request, body: dict[str, Any] = Body(default_factory=dict)):
    from app.application.session_account_meta import (
        audit_admin_action,
        load_session_account_meta,
        persist_session_account_meta,
    )
    from app.enterprise.mod_entitlements import (
        persist_entitlements_to_session_row,
        refresh_session_entitlements_from_market,
        reload_enterprise_mods_after_login,
    )
    from app.fastapi_routes.legacy_helpers import _session_id_from_request
    from app.fastapi_routes.market_account import resolve_valid_market_access_token

    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate
    sid = _session_id_from_request(request)
    target_id = body.get("market_user_id")
    target_name = str(body.get("username") or "").strip()
    if target_id is None:
        return JSONResponse({"success": False, "message": "market_user_id 必填"}, status_code=400)
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return JSONResponse({"success": False, "message": "market_user_id 无效"}, status_code=400)

    meta = load_session_account_meta(sid) or {}
    persist_session_account_meta(
        sid,
        account_kind=str(meta.get("account_kind") or "admin"),
        company_brand=str(meta.get("company_brand") or ""),
        market_user_id=meta.get("market_user_id"),
        market_is_admin=True,
        market_is_enterprise=bool(meta.get("market_is_enterprise")),
        impersonating_market_user_id=target_id,
        impersonating_username=target_name,
    )
    tok = await resolve_valid_market_access_token(sid)
    if tok:
        client_ids = await refresh_session_entitlements_from_market(
            market_token=tok,
            market_user_id=meta.get("market_user_id"),
            market_username=target_name,
            session_id=sid,
        )
        persist_entitlements_to_session_row(sid, client_ids)
        await reload_enterprise_mods_after_login()
    audit_admin_action(
        request,
        "impersonate_start",
        target_user_id=target_id,
        detail=target_name,
    )
    return {
        "success": True,
        "impersonating_market_user_id": target_id,
        "impersonating_username": target_name,
    }


@router.post("/admin/impersonate/end", response_model=None)
async def admin_end_impersonate(request: Request):
    from app.application.session_account_meta import (
        audit_admin_action,
        clear_impersonation,
        load_session_account_meta,
    )
    from app.enterprise.mod_entitlements import (
        persist_entitlements_to_session_row,
        refresh_session_entitlements_from_market,
        reload_enterprise_mods_after_login,
    )
    from app.fastapi_routes.legacy_helpers import _session_id_from_request
    from app.fastapi_routes.market_account import resolve_valid_market_access_token

    gate = _require_market_admin_session(request)
    if gate is not None:
        return gate
    sid = _session_id_from_request(request)
    meta = load_session_account_meta(sid) or {}
    clear_impersonation(sid)
    tok = await resolve_valid_market_access_token(sid)
    if tok:
        client_ids = await refresh_session_entitlements_from_market(
            market_token=tok,
            market_user_id=meta.get("market_user_id"),
            session_id=sid,
        )
        persist_entitlements_to_session_row(sid, client_ids)
        await reload_enterprise_mods_after_login()
    audit_admin_action(request, "impersonate_end")
    return {"success": True}


@router.get("/admin/modules", response_model=None)
async def list_modules():
    """获取 XCmax 模块注册表（核心 + 本地 Mod + 员工包）。"""
    modules: list[dict[str, Any]] = list(CORE_MODULES)
    modules.extend(_collect_mod_modules())
    modules.extend(_collect_employee_pack_modules())
    return {"success": True, "data": modules, "total": len(modules)}


@router.get("/admin/daily-digests", response_model=None)
async def list_daily_digests(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """从服务器读取已保存的每日摘要邮件副本。"""
    return await _market_admin_proxy(
        request,
        "GET",
        f"/api/agent/butler/daily-digests?limit={limit}&offset={offset}",
    )


@router.get("/admin/daily-digests/{record_id}", response_model=None)
async def get_daily_digest(request: Request, record_id: int):
    """从服务器读取单条每日摘要完整正文。"""
    return await _market_admin_proxy(
        request,
        "GET",
        f"/api/agent/butler/daily-digests/{record_id}",
    )


@router.post("/admin/all-hands-report/sessions", response_model=None)
async def start_all_hands_report_session(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
):
    """启动服务器员工大会后台会话，返回远端 session_id。"""
    return await _market_admin_proxy(
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
    return await _market_admin_proxy(
        request,
        "GET",
        f"/api/workbench/sessions/{sid}",
    )


def _probe_remote_health_sync() -> dict[str, Any]:
    """同步探测远端 HTTP /api/health；供 asyncio.to_thread 调用，避免阻塞事件循环。"""
    remote_url = f"http://{REMOTE_HOST}:{REMOTE_PORT}/api/health"
    t0 = time.time()
    try:
        req = urllib.request.Request(remote_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            latency_ms = round((time.time() - t0) * 1000)
            body = json.loads(resp.read(4096).decode("utf-8", errors="replace"))
            return {
                "success": True,
                "data": {
                    "reachable": True,
                    "latency_ms": latency_ms,
                    "version": body.get("version") or body.get("git_sha") or "",
                    "deploy_time": body.get("timestamp") or "",
                    "host": REMOTE_HOST,
                    "port": REMOTE_PORT,
                },
            }
    except Exception as exc:
        logger.debug("remote_status probe failed: %s", exc)
        return {
            "success": True,
            "data": {
                "reachable": False,
                "latency_ms": None,
                "version": "",
                "deploy_time": "",
                "host": REMOTE_HOST,
                "port": REMOTE_PORT,
                "error": str(exc),
            },
        }


@router.get("/admin/remote-status", response_model=None)
async def remote_status():
    """探测远端服务器连接状态（轻量 HTTP GET /api/health）。"""
    return await asyncio.to_thread(_probe_remote_health_sync)


@router.get("/sync/status", response_model=None)
async def sync_status():
    """获取双向同步健康状态。"""
    try:
        from app.db.xcmax_sync import SyncDb
        db = SyncDb()
        info = db.get_status()
        return {"success": True, "data": info}
    except Exception as exc:
        logger.debug("sync_status db read failed: %s", exc)
        return {
            "success": True,
            "data": {
                "healthy": False,
                "local_cursor": None,
                "remote_cursor": None,
                "outbox_count": 0,
                "last_sync_at": None,
                "conflict_count": 0,
                "note": "同步数据库尚未初始化，请先完成 sync-foundation 阶段。",
            },
        }


@router.post("/sync/push", response_model=None)
async def sync_push():
    """触发本地 outbox 向服务器推送。"""
    try:
        from app.application.xcmax_sync_app import push_outbox

        result = push_outbox(remote_host=REMOTE_HOST, remote_port=REMOTE_PORT)
        return {"success": True, "data": result}
    except Exception as exc:
        logger.warning("sync_push failed: %s", exc)
        return JSONResponse(
            {"success": False, "message": f"推送失败: {exc}"},
            status_code=500,
        )


@router.get("/sync/changes", response_model=None)
async def sync_changes(since_cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    """获取变更日志（支持断线补拉）。"""
    try:
        from app.db.xcmax_sync import SyncDb
        db = SyncDb()
        rows = db.get_changes(since_cursor=since_cursor, limit=limit)
        return {"success": True, "data": rows, "count": len(rows)}
    except Exception as exc:
        logger.debug("sync_changes read failed: %s", exc)
        return {"success": True, "data": [], "count": 0, "note": str(exc)}


@router.post("/sync/receive", response_model=None)
async def sync_receive(body: dict | list):
    """接收远端推来的变更，写入 inbox，立即尝试应用，并记录审计日志。"""
    try:
        from app.db.xcmax_sync import SyncDb
        db = SyncDb()
        items = body if isinstance(body, list) else [body]
        written = db.enqueue_inbox(items)
        try:
            from app.application.xcmax_sync_app import apply_inbox

            result = apply_inbox(limit=len(items) + 50)
        except Exception as ae:
            result = {"applied": 0, "error": str(ae)}
        # 写审计事件
        try:
            from app.mod_sdk.audit import write_audit_event
            write_audit_event(
                action="xcmax.sync.receive",
                details={"received": written, "apply": result},
            )
        except Exception:
            pass
        return {"success": True, "received": written, "apply_result": result}
    except Exception as exc:
        logger.warning("sync_receive failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.post("/sync/pull", response_model=None)
async def sync_pull():
    """主动从远端拉取增量变更并应用到本地。"""
    try:
        from app.application.xcmax_sync_app import apply_inbox, pull_from_remote

        pull_result = pull_from_remote(remote_host=REMOTE_HOST, remote_port=REMOTE_PORT)
        apply_result = apply_inbox()
        return {"success": True, "data": {"pull": pull_result, "apply": apply_result}}
    except Exception as exc:
        logger.warning("sync_pull failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


# ---------------------------------------------------------------------------
# 专用实时同步流 (SSE) — 独立于 AI chat streaming
# ---------------------------------------------------------------------------

SYNC_POLL_INTERVAL_S = float(os.environ.get("XCMAX_SYNC_POLL_S", "10"))


async def _sync_sse_generator(request: Request, since_cursor: int):
    """持续产生 SSE 事件：每隔 SYNC_POLL_INTERVAL_S 秒检查一次本地变更日志。"""
    import json as _json
    cursor = since_cursor
    connected = _json.dumps({"type": "connected", "cursor": since_cursor}, ensure_ascii=False)
    yield f"data: {connected}\n\n"
    while True:
        if await request.is_disconnected():
            break
        try:
            from app.db.xcmax_sync import SyncDb
            db = SyncDb()
            rows = db.get_changes(since_cursor=cursor, limit=50)
            if rows:
                cursor = rows[-1]["id"]
                data = _json.dumps({"cursor": cursor, "changes": rows}, ensure_ascii=False, default=str)
                yield f"data: {data}\n\n"
            else:
                status = db.get_status()
                heartbeat = _json.dumps({"type": "heartbeat", "cursor": cursor, "status": status}, ensure_ascii=False, default=str)
                yield f"data: {heartbeat}\n\n"
        except Exception as exc:
            err = _json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {err}\n\n"
        await asyncio.sleep(SYNC_POLL_INTERVAL_S)


@router.get("/sync/conflicts", response_model=None)
async def list_conflicts(limit: int = Query(50, ge=1, le=500)):
    """列出 inbox 中待处理的冲突条目。"""
    try:
        from app.db.xcmax_sync import _resolve_db_path
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(str(_resolve_db_path()))
        conn.row_factory = _sqlite3.Row
        rows = conn.execute(
            "SELECT id, entity_type, entity_id, operation, payload_json, conflict_note, received_at "
            "FROM sync_inbox WHERE status='conflict' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        import json as _json
        data = []
        for row in rows:
            d = dict(row)
            try:
                d["payload"] = _json.loads(d.pop("payload_json") or "{}")
            except Exception:
                d["payload"] = {}
            data.append(d)
        return {"success": True, "data": data, "count": len(data)}
    except Exception as exc:
        return {"success": True, "data": [], "count": 0, "note": str(exc)}


@router.post("/sync/conflicts/{inbox_id}/resolve", response_model=None)
async def resolve_conflict(inbox_id: int, body: dict):
    """手动解决指定冲突（action: 'apply' | 'skip'）。"""
    action = str(body.get("action") or "skip").strip()
    try:
        from app.db.xcmax_sync import SyncDb
        db = SyncDb()
        if action == "apply":
            from app.db.xcmax_sync import _resolve_db_path
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(str(_resolve_db_path()))
            conn.row_factory = _sqlite3.Row
            row = conn.execute(
                "SELECT entity_type, entity_id, operation, payload_json FROM sync_inbox WHERE id=?",
                (inbox_id,),
            ).fetchone()
            conn.close()
            if row:
                import json as _json
                from app.application.xcmax_sync_app import entity_appliers

                _ENTITY_APPLIERS = entity_appliers()
                item = {
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "operation": row["operation"],
                    "payload": _json.loads(row["payload_json"] or "{}"),
                }
                applier = _ENTITY_APPLIERS.get(row["entity_type"])
                if applier:
                    applier(item)
            db.mark_inbox_applied(inbox_id)
        else:
            from app.db.xcmax_sync import _resolve_db_path
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(str(_resolve_db_path()))
            conn.execute("UPDATE sync_inbox SET status='skipped' WHERE id=?", (inbox_id,))
            conn.commit()
            conn.close()
        return {"success": True, "inbox_id": inbox_id, "action": action}
    except Exception as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/sync/stream", response_model=None)
async def sync_stream(
    request: Request,
    since_cursor: int = Query(0, ge=0),
):
    """专用 SSE 同步流：服务端实时推送本地变更（与 AI chat streaming 完全分离）。

    客户端监听示例：
        const es = new EventSource('/api/xcmax/sync/stream?since_cursor=0')
        es.onmessage = e => { const d = JSON.parse(e.data); console.log(d) }
    """
    return StreamingResponse(
        _sync_sse_generator(request, since_cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
