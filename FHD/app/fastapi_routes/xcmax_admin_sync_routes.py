"""XCmax admin sync routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

import app.fastapi_routes.xcmax_admin_patch as _p

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/sync/status", response_model=None)
async def sync_status():
    """获取双向同步健康状态。"""
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        info = db.get_status()
        return {"success": True, "data": info}
    except _p.RECOVERABLE_ERRORS as exc:
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

        result = push_outbox(remote_host=_p.REMOTE_HOST, remote_port=_p.REMOTE_PORT)
        return {"success": True, "data": result}
    except _p.RECOVERABLE_ERRORS as exc:
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
    except _p.RECOVERABLE_ERRORS as exc:
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
        except _p.RECOVERABLE_ERRORS as ae:
            result = {"applied": 0, "error": str(ae)}
        # 写审计事件
        try:
            from app.mod_sdk.audit import write_audit_event

            write_audit_event(
                actor=None,
                action="xcmax.sync.receive",
                payload={"received": written, "apply": result},
            )
        except _p.RECOVERABLE_ERRORS:
            pass
        return {"success": True, "received": written, "apply_result": result}
    except _p.RECOVERABLE_ERRORS as exc:
        logger.warning("sync_receive failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

@router.post("/sync/pull", response_model=None)
async def sync_pull():
    """主动从远端拉取增量变更并应用到本地。"""
    try:
        from app.application.xcmax_sync_app import apply_inbox, pull_from_remote

        pull_result = pull_from_remote(remote_host=_p.REMOTE_HOST, remote_port=_p.REMOTE_PORT)
        apply_result = apply_inbox()
        return {"success": True, "data": {"pull": pull_result, "apply": apply_result}}
    except _p.RECOVERABLE_ERRORS as exc:
        logger.warning("sync_pull failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

@router.get("/sync/entitlements/current", response_model=None)
async def sync_current_entitlements(request: Request):
    """读取当前登录账号最近一次收到的账号权益强推快照。

    企业端侧边栏用它判断管理端是否已经向本机账号推送了新权益。该接口只读，不进入
    管理员代管态，也不改变当前登录身份。
    """
    try:
        from app.application.session_account_meta import load_session_account_meta
        from app.application.xcmax_sync_app import read_sync_meta
        from app.fastapi_routes.domains.misc.helpers import _session_id_from_request

        sid = _session_id_from_request(request)
        meta = load_session_account_meta(sid) if sid else None
        if not meta:
            return {
                "success": True,
                "data": {
                    "has_snapshot": False,
                    "account": None,
                    "snapshot": None,
                    "updated_at_ms": 0,
                    "note": "no active session",
                },
            }

        market_user_id = meta.get("impersonating_market_user_id") or meta.get("market_user_id")
        username_candidates = [
            str(meta.get("impersonating_username") or "").strip(),
            str(meta.get("company_brand") or "").strip(),
        ]
        try:
            from app.infrastructure.auth.dependencies import resolve_session_user

            user = resolve_session_user(request)
            if user is not None:
                username_candidates.append(str(getattr(user, "username", "") or "").strip())
                username_candidates.append(str(getattr(user, "display_name", "") or "").strip())
        except _p.RECOVERABLE_ERRORS:
            pass

        snapshots: list[dict[str, Any]] = []
        if market_user_id not in (None, ""):
            snap = read_sync_meta(f"account_entitlements:{market_user_id}")
            if snap:
                snapshots.append(snap)
        for username in username_candidates:
            if not username:
                continue
            snap = read_sync_meta(f"account_entitlements:username:{username}")
            if snap:
                snapshots.append(snap)

        def _snap_updated_at_ms(snapshot: dict[str, Any]) -> int:
            meta_obj = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
            try:
                return int(meta_obj.get("updated_at_ms") or 0)
            except (TypeError, ValueError):
                return 0

        snapshot = max(snapshots, key=_snap_updated_at_ms) if snapshots else None
        updated_at_ms = _snap_updated_at_ms(snapshot or {})
        return {
            "success": True,
            "data": {
                "has_snapshot": bool(snapshot),
                "account": {
                    "market_user_id": market_user_id,
                    "username": next((u for u in username_candidates if u), ""),
                    "account_kind": meta.get("account_kind"),
                    "market_is_enterprise": bool(meta.get("market_is_enterprise")),
                    "market_is_admin": bool(meta.get("market_is_admin")),
                },
                "snapshot": snapshot,
                "updated_at_ms": updated_at_ms,
            },
        }
    except _p.RECOVERABLE_ERRORS as exc:
        logger.warning("sync_current_entitlements failed: %s", exc)
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)


@router.get("/sync/conflicts", response_model=None)
async def list_conflicts(limit: int = Query(50, ge=1, le=500)):
    """列出 inbox 中待处理的冲突条目。"""
    try:
        from app.application.admin_sync_app_service import list_admin_sync_conflicts

        data = list_admin_sync_conflicts(limit=limit)
        return {"success": True, "data": data, "count": len(data)}
    except Exception as exc:  # noqa: BLE001
        return {"success": True, "data": [], "count": 0, "note": str(exc)}

@router.post("/sync/conflicts/{inbox_id}/resolve", response_model=None)
async def resolve_conflict(inbox_id: int, body: dict):
    """手动解决指定冲突（action: 'apply' | 'skip'）。"""
    action = str(body.get("action") or "skip").strip()
    try:
        from app.db.xcmax_sync import SyncDb

        db = SyncDb()
        if action == "apply":
            from app.application.admin_sync_app_service import fetch_admin_inbox_row
            from app.application.xcmax_sync_app import entity_appliers

            row = fetch_admin_inbox_row(inbox_id)
            if row:
                applier = entity_appliers().get(row["entity_type"])
                if applier:
                    applier(row)
            db.mark_inbox_applied(inbox_id)
        else:
            from app.application.admin_sync_app_service import mark_admin_inbox_skipped

            mark_admin_inbox_skipped(inbox_id)
        return {"success": True, "inbox_id": inbox_id, "action": action}
    except Exception as exc:  # noqa: BLE001
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
        _p._sync_sse_generator(request, since_cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
