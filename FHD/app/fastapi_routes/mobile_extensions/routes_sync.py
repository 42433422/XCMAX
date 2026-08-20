"""Mobile sync routes (strangler extract)."""

from __future__ import annotations

import importlib
import logging
from typing import Any, cast

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions.models import (
    SyncAckBody,
    SyncPullBody,
    SyncPushBody,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
router: APIRouter = APIRouter()


def _parent():
    return importlib.import_module("app.fastapi_routes.mobile_api_extensions")


def _ai_circle_employee_profiles():
    return _parent()._ai_circle_employee_profiles()


def _ai_circle_user(user):
    return _parent()._ai_circle_user(user)


def _ai_conversation_changes(user, *, limit: int):
    return _parent()._ai_conversation_changes(user, limit=limit)


def _approval_items():
    return _parent()._approval_items()


def _safe_mobile_sync_items(label: str, loader):
    return _parent()._safe_mobile_sync_items(label, loader)


def _shipment_items():
    return _parent()._shipment_items()


# ── 同步 ──


def _mobile_sync_runtime_contract() -> dict[str, Any]:
    return {
        "source": "cloud",
        "sync_mode": "cloud",
        "standalone_supported": True,
        "desktop_required": False,
        "executor_required": False,
        "mobile_flow_parity": True,
        "offline_cache_supported": True,
        "desktop_executor": {
            "required": False,
            "role": "optional_local_executor",
            "required_for": ["local_files", "local_cli", "local_printing", "lan_devices"],
        },
    }


async def _mobile_sync_circle_posts(user: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    parent = _parent()
    override = getattr(parent, "_mobile_sync_circle_posts", None)
    if override is not None and override is not _mobile_sync_circle_posts:
        return cast("list[dict[str, Any]]", await override(user, limit=limit))
    try:
        import importlib

        from app.application.ai_circle_service import list_posts

        employee_circle_sync = importlib.import_module("app.application.employee_circle_sync")
        try:
            await employee_circle_sync.sync_modstore_reports()
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - 交流圈同步是拉取增强项，不能拖垮整次手机同步
            logger.warning("mobile sync: circle modstore report sync skipped", exc_info=True)

        uid, _, _ = _ai_circle_user(user)
        posts = list_posts(user_id=uid, limit=limit)
        profiles = _ai_circle_employee_profiles()
        for post in posts:
            profile = profiles.get(str(post.get("employee_id") or ""))
            if profile:
                post["author_name"] = profile["name"]
                post["author_avatar"] = profile["avatar"] or post.get("author_avatar")
        return posts
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001 - 手机同步的其他数据不能被交流圈投影拖垮
        logger.warning("mobile sync: circle posts skipped: %s", exc)
        return []


@router.get("/sync/status")
async def mobile_sync_status(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb, _ensure_schema, _get_conn

        db = SyncDb()
        st = dict(db.get_status())
        with _get_conn() as conn:
            _ensure_schema(conn)
            st["inbox_pending"] = conn.execute(
                "SELECT COUNT(*) FROM sync_inbox WHERE status='pending'",
            ).fetchone()[0]
    except RECOVERABLE_ERRORS:
        st = {"error": "同步服务健康检查失败", "healthy": False}
    st.update(_mobile_sync_runtime_contract())
    return format_mobile_response(data=st)


@router.post("/sync/pull")
async def mobile_sync_pull(body: SyncPullBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        changes = sync_db.get_changes(since_cursor=body.since_cursor, limit=200)
        cursor = sync_db.get_status().get("local_cursor") or body.since_cursor
        if cursor:
            sync_db.update_remote_cursor(int(cursor))
        im_entity_types = {"im_message", "im_read_state"}
        im_changes = [c for c in changes if str(c.get("entity_type") or "") in im_entity_types]
        ai_changes = _ai_conversation_changes(user, limit=100)
        circle_posts = await _mobile_sync_circle_posts(user, limit=50)
        approvals = _safe_mobile_sync_items("approvals", _approval_items)
        shipments = _safe_mobile_sync_items("shipments", _shipment_items)
        return format_mobile_response(
            data={
                **_mobile_sync_runtime_contract(),
                "cursor": cursor,
                "changes": changes,
                "im_changes": im_changes,
                "im_change_count": len(im_changes),
                "ai_changes": ai_changes,
                "ai_change_count": len(ai_changes),
                "circle_posts": circle_posts,
                "circle_post_count": len(circle_posts),
                "approvals": approvals,
                "shipments": shipments,
            },
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning("mobile_sync_pull: %s", exc)
        return JSONResponse(
            format_mobile_response(None, "同步服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/sync/push")
async def mobile_sync_push(body: SyncPushBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    actor = getattr(user, "username", None) or f"user-{getattr(user, 'id', 0)}"
    written = 0
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        for item in body.items[:50]:
            sync_db.append_change(
                item.entity_type,
                item.entity_id,
                item.operation,
                item.payload,
                actor=actor,
                origin_node="mobile",
            )
            written += 1
        apply_result: dict[str, Any] = {}
        try:
            from app.application.xcmax_sync_app import apply_inbox

            apply_result = apply_inbox(limit=written + 50) or {}
        except RECOVERABLE_ERRORS:
            apply_result = {"error": "同步结果应用失败"}
        return format_mobile_response(data={"written": written, "apply": apply_result})
    except RECOVERABLE_ERRORS as exc:
        logger.warning("mobile_sync_push: %s", exc)
        return JSONResponse(
            format_mobile_response(None, "同步服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.post("/sync/ack")
async def mobile_sync_ack(body: SyncAckBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    try:
        from app.db.xcmax_sync import SyncDb

        sync_db = SyncDb()
        sync_db.update_remote_cursor(int(body.cursor))
        return format_mobile_response(data={"acked": int(body.cursor)})
    except RECOVERABLE_ERRORS as exc:
        logger.warning("mobile_sync_ack: %s", exc)
        return JSONResponse(
            format_mobile_response(None, "同步服务暂不可用", success=False, code=500),
            status_code=500,
        )


@router.get("/sync/conflicts")
async def mobile_sync_conflicts(user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    items: list[dict[str, Any]] = []
    try:
        from app.db.xcmax_sync import _ensure_schema, _get_conn

        with _get_conn() as conn:
            _ensure_schema(conn)
            rows = conn.execute(
                """
                SELECT id, entity_type, entity_id, conflict_note, received_at
                FROM sync_inbox WHERE status='conflict' ORDER BY id DESC LIMIT 50
                """,
            ).fetchall()
            items = [dict(r) for r in rows]
    except RECOVERABLE_ERRORS:
        return format_mobile_response(data={"items": [], "error": "同步记录暂不可用"})
    return format_mobile_response(data={"items": items})
